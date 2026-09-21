import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID, ObjectIdentifier

from .domain import AppError, validate_cnpj


def run_store(action: str, payload=None) -> str:
    if os.name != "nt":
        raise AppError("O repositório de certificados requer Windows.")
    executable = (
        Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    try:
        result = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(Path(__file__).with_name("windows_store.ps1")),
                "-Action",
                action,
            ],
            input=json.dumps(payload) if payload else "",
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppError("Não foi possível acessar o certificado/SEFAZ dentro do prazo.") from exc
    if result.returncode:
        raise AppError("Falha no Windows: verifique certificado, driver/PIN, política de scripts e conexão.")
    return result.stdout.lstrip("\ufeff").strip()


def der_text(value: bytes) -> str:
    """Lê o valor DER textual do OtherName ICP-Brasil, sem buscar números arbitrários."""
    if len(value) < 2 or value[0] not in {0x0C, 0x13, 0x16, 0x04}:
        raise ValueError("Tipo DER não suportado")
    length, start = value[1], 2
    if length & 0x80:
        count = length & 0x7F
        if not 1 <= count <= 4 or len(value) < 2 + count:
            raise ValueError("DER inválido")
        length, start = int.from_bytes(value[2 : 2 + count], "big"), 2 + count
    if len(value) != start + length:
        raise ValueError("Comprimento DER inválido")
    return value[start:].decode("utf-8")


def certificate_cnpj(cert: x509.Certificate) -> str:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for name in san.get_values_for_type(x509.OtherName):
            if name.type_id == ObjectIdentifier("2.16.76.1.3.3"):
                return validate_cnpj(der_text(name.value))
    except (x509.ExtensionNotFound, ValueError, AppError):
        pass
    # Compatibilidade com e-CNPJ cujo CN termina em ':CNPJ'.
    for name in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
        match = re.search(r":\s*([A-Z0-9]{12}\d{2})$", name.value.upper())
        if match:
            return validate_cnpj(match[1])
    raise AppError("Não foi possível identificar um e-CNPJ no certificado.")


@dataclass(frozen=True)
class Certificate:
    store: str
    thumbprint: str
    subject: str
    cnpj: str
    valid_from: datetime
    valid_to: datetime

    def check(self):
        if not self.valid_from <= datetime.now(UTC) <= self.valid_to:
            raise AppError("O certificado selecionado está fora da validade.")

    @property
    def label(self):
        return f"{self.subject} | {self.cnpj} | até {self.valid_to:%d/%m/%Y} | {self.store} | {self.thumbprint[-8:]}"


def list_certificates() -> list[Certificate]:
    raw = json.loads(run_store("list") or "[]")
    result = []
    for entry in raw:
        try:
            cert = x509.load_der_x509_certificate(base64.b64decode(entry["der"]))
            cnpj = certificate_cnpj(cert)
            names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            result.append(
                Certificate(
                    entry["store"],
                    entry["thumbprint"],
                    names[0].value if names else cnpj,
                    cnpj,
                    cert.not_valid_before_utc,
                    cert.not_valid_after_utc,
                )
            )
        except (ValueError, AppError):
            continue
    return sorted(result, key=lambda item: (item.cnpj, item.valid_to), reverse=True)
