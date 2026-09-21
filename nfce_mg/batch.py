import hashlib
import json
import tempfile
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .domain import (
    MAX_XML,
    NS,
    AppError,
    Month,
    parse_xml,
    validate_cancellation,
    validate_cnpj,
    validate_invoice,
)


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(data)
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


class Batch:
    def __init__(
        self,
        output: Path,
        cnpj: str,
        month: Month,
        environment="producao",
        *,
        progress=lambda message: None,
        stop=None,
    ):
        self.cnpj = validate_cnpj(cnpj)
        if environment not in {"producao", "homologacao"}:
            raise AppError("Ambiente fiscal inválido.")
        self.month, self.environment = month, environment
        self.root = Path(output).resolve() / self.cnpj / environment / str(month)
        self.root.mkdir(parents=True, exist_ok=True)
        self.progress = progress
        self.stop = stop or threading.Event()
        self.entries, self.errors, self.files = [], [], set()
        self.cancelled = False
        self.scanned = 0

    def _check_stop(self):
        if self.stop.is_set():
            self.cancelled = True
            raise AppError("Operação interrompida pelo usuário.")

    def _cache(self, client, invoice_id, cancellation=False):
        # O ID é opaco: hash impede traversal; separação inclui ambiente da API.
        digest = hashlib.sha256(f"{client.base}|{invoice_id}|{cancellation}".encode()).hexdigest()
        path = self.root / ".cache" / f"{digest}.xml"
        if path.exists() and path.stat().st_size <= MAX_XML:
            return path, path.read_bytes()
        return path, client.xml(invoice_id, cancellation)

    def _save(self, data, invoice, status, source_id):
        path = self.root / "xml" / f"{invoice.key}-nfe.xml"
        # Duplicatas idênticas são idempotentes; divergência exige revisão.
        if path.exists() and path.read_bytes() != data:
            raise AppError("Já existe XML com a mesma chave e conteúdo diferente; revise os arquivos.")
        atomic_write(path, data)
        self.files.add(path)
        self.entries.append(
            {
                **asdict(invoice),
                "status_origem": status,
                "id_origem": source_id,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    def from_acbr(self, client):
        try:
            self._check_stop()
            for row in client.list_invoices(self.cnpj, self.environment):
                self._check_stop()
                self.scanned += 1
                try:
                    if not self.month.contains(row.get("data_emissao", "")):
                        continue
                    if str(row.get("modelo")) != "65":
                        raise AppError("Listagem contém modelo diferente de NFC-e.")
                    status = row.get("status", "")
                    if status not in {"autorizado", "denegado", "cancelado"}:
                        raise AppError(f"Nota sem XML processado disponível (status {status}).")
                    cache, data = self._cache(client, row["id"])
                    try:
                        invoice = validate_invoice(data, self.cnpj, self.environment)
                    except AppError:
                        cache.unlink(missing_ok=True)
                        raise
                    if row.get("chave") != invoice.key or not self.month.contains(invoice.issued_at):
                        raise AppError("XML diverge da chave ou competência da listagem.")
                    atomic_write(cache, data)
                    self._save(data, invoice, status, row["id"])
                    if status == "cancelado":
                        self._check_stop()
                        cache_event, event = self._cache(client, row["id"], True)
                        try:
                            validate_cancellation(event, invoice.key, self.environment)
                        except AppError:
                            cache_event.unlink(missing_ok=True)
                            raise
                        atomic_write(cache_event, event)
                        event_path = self.root / "eventos" / f"{invoice.key}-cancelamento.xml"
                        atomic_write(event_path, event)
                        self.files.add(event_path)
                    self.progress(f"XML conferido: {invoice.key}")
                except AppError as exc:
                    self.errors.append({"id": row["id"], "erro": str(exc)})
                    self.progress(f"Pendência: {exc}")
                if self.scanned % 100 == 0:
                    self.progress(f"{self.scanned} registros consultados na ACBr.")
        except AppError as exc:
            self.errors.append({"id": "listagem", "erro": str(exc)})
        return self.finish("ACBr API")

    def from_folder(self, folder: Path):
        folder = Path(folder).resolve()
        if not folder.is_dir():
            raise AppError("Escolha uma pasta de XMLs existente.")
        if folder == self.root or folder.is_relative_to(self.root):
            raise AppError("A pasta de origem deve ser diferente da pasta de saída.")
        events = []
        try:
            for path in folder.rglob("*"):
                self._check_stop()
                if (
                    not path.is_file()
                    or path.suffix.lower() != ".xml"
                    or path.resolve().is_relative_to(self.root)
                ):
                    continue
                self.scanned += 1
                try:
                    if path.stat().st_size > MAX_XML:
                        raise AppError("XML excede 10 MB.")
                    data = path.read_bytes()
                    root = parse_xml(data)
                    if root.tag == f"{{{NS['n']}}}procEventoNFe":
                        events.append(path)
                        continue
                    invoice = validate_invoice(data, self.cnpj, self.environment)
                    if self.month.contains(invoice.issued_at):
                        self._save(data, invoice, "protocolo local; situação atual não consultada", path.name)
                        self.progress(f"Importado: {invoice.key}")
                except (AppError, OSError) as exc:
                    self.errors.append({"id": path.name, "erro": str(exc)})
            keys = {entry["key"] for entry in self.entries}
            for path in events:
                self._check_stop()
                try:
                    data = path.read_bytes()
                    root = parse_xml(data)
                    key = root.findtext("n:evento/n:infEvento/n:chNFe", "", NS)
                    if key not in keys:
                        continue
                    validate_cancellation(data, key, self.environment)
                    dest = self.root / "eventos" / f"{key}-cancelamento.xml"
                    atomic_write(dest, data)
                    self.files.add(dest)
                    for entry in self.entries:
                        if entry["key"] == key:
                            entry["status_origem"] = "cancelado (evento local)"
                except (AppError, OSError) as exc:
                    self.errors.append({"id": path.name, "erro": str(exc)})
        except AppError as exc:
            self.errors.append({"id": "importação", "erro": str(exc)})
        return self.finish("Pasta do emissor/ERP")

    def finish(self, source):
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        report = {
            "origem": source,
            "cnpj": self.cnpj,
            "competencia": str(self.month),
            "ambiente": self.environment,
            "interrompido": self.cancelled,
            "resultado": "parcial" if self.errors or self.cancelled else "concluido",
            "registros_examinados": self.scanned,
            "xmls": len({e["key"] for e in self.entries}),
            "documentos": self.entries,
            "erros": self.errors,
            "observacao": "Cobertura limitada à origem consultada. Não comprova totalidade das emissões na SEFAZ."
            " Validação estrutural; assinatura digital e XSD não verificados.",
        }
        manifest = self.root / f"relatorio-{run_id}.json"
        atomic_write(manifest, json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
        archive = self.root / f"nfce-{self.cnpj}-{self.month}-{run_id}.zip"
        temporary = archive.with_suffix(".tmp")
        try:
            with ZipFile(temporary, "w", ZIP_DEFLATED) as output:
                output.write(manifest, manifest.name)
                # Só inclui documentos validados nesta execução, nunca arquivos antigos por glob.
                for path in sorted(self.files):
                    output.write(path, path.relative_to(self.root).as_posix())
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
        report["arquivo_zip"] = str(archive)
        report["relatorio"] = str(manifest)
        self.progress(f"Lote {report['resultado']}: {report['xmls']} XMLs; {len(self.errors)} pendências.")
        return report
