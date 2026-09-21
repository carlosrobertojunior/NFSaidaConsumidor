import pytest
from conftest import CNPJ, make_key, make_xml

from nfce_mg.certificates import certificate_cnpj, der_text
from nfce_mg.domain import AppError, Month, validate_cnpj, validate_invoice, validate_key


def test_cnpj_and_certificate(certificate):
    assert validate_cnpj("11.222.333/0001-81") == CNPJ
    assert certificate_cnpj(certificate) == CNPJ
    with pytest.raises(AppError):
        validate_cnpj("11.222.333/0001-82")


def test_der_rejects_arbitrary_or_truncated_content():
    with pytest.raises(ValueError):
        der_text(b"random 11222333000181")
    with pytest.raises(ValueError):
        der_text(b"\x0c\x0e123")


def test_month_uses_mg_timezone_and_leap_year():
    month = Month.parse("2026-08")
    assert month.contains("2026-09-01T02:59:59Z")
    assert not month.contains("2026-09-01T03:00:00Z")
    assert Month.parse("2024-02").contains("2024-02-29T12:00:00-03:00")
    for invalid in ["2026-13", "2026-00", "2026-1", "../../test"]:
        with pytest.raises(AppError):
            Month.parse(invalid)
    with pytest.raises(AppError):
        month.contains("2026-08-01T00:00:00")


def test_invoice_accepts_processed_mg_output():
    invoice = validate_invoice(make_xml(), CNPJ, "producao")
    assert invoice.key == make_key()
    assert invoice.total == "12.34"


@pytest.mark.parametrize(
    "old,new",
    [
        (b"<mod>65</mod>", b"<mod>55</mod>"),
        (b"<cUF>31</cUF>", b"<cUF>35</cUF>"),
        (b"<tpNF>1</tpNF>", b"<tpNF>0</tpNF>"),
        (b"<tpAmb>1</tpAmb>", b"<tpAmb>2</tpAmb>"),
        (b"<cStat>100</cStat>", b"<cStat>204</cStat>"),
        (b"<CNPJ>11222333000181</CNPJ>", b"<CNPJ>12345678000195</CNPJ>"),
    ],
)
def test_invoice_rejects_mismatch(old, new):
    with pytest.raises(AppError):
        validate_invoice(make_xml().replace(old, new), CNPJ, "producao")


def test_rejects_protocol_alone_and_entity():
    for xml in [
        b'<protNFe xmlns="http://www.portalfiscal.inf.br/nfe"/>',
        b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>',
    ]:
        with pytest.raises(AppError):
            validate_invoice(xml, CNPJ, "producao")


def test_key_checks_model_uf_cnpj_and_digit():
    validate_key(make_key(), CNPJ)
    for key in [make_key(model="55"), make_key(uf="35"), make_key()[:-1] + "9"]:
        with pytest.raises(AppError):
            validate_key(key, CNPJ)
