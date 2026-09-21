import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from defusedxml import ElementTree as ET

NS = {"n": "http://www.portalfiscal.inf.br/nfe"}
MG = ZoneInfo("America/Sao_Paulo")
MAX_XML = 10 * 1024 * 1024


class AppError(Exception):
    """Mensagem segura para exibição, sem segredos de transporte."""


def validate_cnpj(value: str) -> str:
    value = re.sub(r"[./\s-]", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", value) or len(set(value)) == 1:
        raise AppError("CNPJ inválido.")
    # Compatível com o cálculo dos CNPJs numéricos e alfanuméricos.
    for size, weights in (
        (12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
        (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)),
    ):
        rest = sum((ord(c) - 48) * w for c, w in zip(value[:size], weights)) % 11
        if int(value[size]) != (0 if rest < 2 else 11 - rest):
            raise AppError("Dígitos verificadores do CNPJ inválidos.")
    return value


@dataclass(frozen=True)
class Month:
    year: int
    month: int

    def __post_init__(self):
        date(self.year, self.month, 1)

    @classmethod
    def parse(cls, value):
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            raise AppError("Informe a competência como AAAA-MM.")
        try:
            return cls(*map(int, value.split("-")))
        except ValueError as exc:
            raise AppError("Competência inválida.") from exc

    @classmethod
    def previous(cls):
        today = datetime.now(MG).date()
        previous = today.replace(day=1) - timedelta(days=1)
        return cls(previous.year, previous.month)

    def contains(self, value: str) -> bool:
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                raise ValueError("sem fuso")
            dt = dt.astimezone(MG)
            return (dt.year, dt.month) == (self.year, self.month)
        except (ValueError, AttributeError) as exc:
            raise AppError("Data de emissão ausente, inválida ou sem fuso horário.") from exc

    def __str__(self):
        return f"{self.year:04d}-{self.month:02d}"


def validate_key(key: str, cnpj: str | None = None):
    if not re.fullmatch(r"\d{44}", key):
        raise AppError("A chave deve conter 44 dígitos.")
    rest = sum(int(c) * (2 + i % 8) for i, c in enumerate(reversed(key[:43]))) % 11
    digit = 0 if rest in (0, 1) else 11 - rest
    if int(key[-1]) != digit or key[:2] != "31" or key[20:22] != "65":
        raise AppError("Chave inválida ou diferente de NFC-e de Minas Gerais.")
    if cnpj and key[6:20] != cnpj:
        raise AppError("A chave pertence a outro emitente.")


def parse_xml(data: bytes):
    if len(data) > MAX_XML:
        raise AppError("XML excede o limite de 10 MB.")
    try:
        return ET.fromstring(data, forbid_dtd=True)
    except Exception as exc:
        raise AppError("XML inválido ou com declarações não permitidas.") from exc


@dataclass(frozen=True)
class Invoice:
    key: str
    issued_at: str
    status: str
    total: str


def validate_invoice(data: bytes, cnpj: str, environment: str) -> Invoice:
    root = parse_xml(data)
    if root.tag != f"{{{NS['n']}}}nfeProc":
        raise AppError("É necessário o XML processado nfeProc, com nota e protocolo.")
    inf = root.find("n:NFe/n:infNFe", NS)
    prot = root.find("n:protNFe/n:infProt", NS)
    if inf is None or prot is None:
        raise AppError("XML sem nota ou protocolo de autorização.")
    key = inf.get("Id", "").removeprefix("NFe")
    validate_key(key, cnpj)

    def value(path):
        return inf.findtext(path, "", NS)

    env = "1" if environment == "producao" else "2"
    if (
        value("n:emit/n:CNPJ") != cnpj
        or value("n:ide/n:mod") != "65"
        or value("n:ide/n:cUF") != "31"
        or value("n:ide/n:tpNF") != "1"
        or value("n:ide/n:tpAmb") != env
    ):
        raise AppError("XML não corresponde ao emitente, saída NFC-e MG ou ambiente selecionado.")
    if prot.findtext("n:chNFe", "", NS) != key or prot.findtext("n:tpAmb", "", NS) != env:
        raise AppError("Protocolo incompatível com a nota.")
    status = prot.findtext("n:cStat", "", NS)
    if status not in {"100", "150", "110", "301", "302", "303"}:
        raise AppError("Protocolo sem autorização ou denegação reconhecida.")
    if not prot.findtext("n:nProt", "", NS):
        raise AppError("Protocolo sem número.")
    issued = value("n:ide/n:dhEmi")
    Month.previous().contains(issued)  # Valida formato, independentemente da competência.
    return Invoice(key, issued, status, value("n:total/n:ICMSTot/n:vNF"))


def validate_cancellation(data: bytes, key: str, environment: str):
    root = parse_xml(data)
    if root.tag != f"{{{NS['n']}}}procEventoNFe":
        raise AppError("Cancelamento sem XML processado procEventoNFe.")
    env = "1" if environment == "producao" else "2"
    for path in ("n:evento/n:infEvento", "n:retEvento/n:infEvento"):
        info = root.find(path, NS)
        if (
            info is None
            or info.findtext("n:chNFe", "", NS) != key
            or info.findtext("n:tpEvento", "", NS) not in {"110111", "110112"}
            or info.findtext("n:tpAmb", "", NS) != env
        ):
            raise AppError("Evento de cancelamento incompatível com a nota.")
    if root.findtext("n:retEvento/n:infEvento/n:cStat", "", NS) not in {"135", "155"}:
        raise AppError("Cancelamento não homologado/vinculado à nota.")
