from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier

CNPJ = "11222333000181"


def make_key(cnpj=CNPJ, model="65", uf="31", number="000000001"):
    partial = uf + "2608" + cnpj + model + "001" + number + "1" + "12345678"
    rest = sum(int(c) * (2 + i % 8) for i, c in enumerate(reversed(partial))) % 11
    return partial + str(0 if rest in (0, 1) else 11 - rest)


def make_xml(key=None, cnpj=CNPJ, date="2026-08-31T23:59:59-03:00", env="1"):
    key = key or make_key(cnpj)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
<NFe><infNFe Id="NFe{key}"><ide><cUF>31</cUF><mod>65</mod><tpNF>1</tpNF>
<tpAmb>{env}</tpAmb><dhEmi>{date}</dhEmi></ide><emit><CNPJ>{cnpj}</CNPJ></emit>
<total><ICMSTot><vNF>12.34</vNF></ICMSTot></total></infNFe></NFe>
<protNFe><infProt><tpAmb>{env}</tpAmb><chNFe>{key}</chNFe><cStat>100</cStat>
<nProt>131260000000001</nProt></infProt></protNFe></nfeProc>""".encode()


def make_event(key=None):
    key = key or make_key()
    return f"""<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe">
<evento><infEvento><tpAmb>1</tpAmb><chNFe>{key}</chNFe><tpEvento>110111</tpEvento></infEvento></evento>
<retEvento><infEvento><tpAmb>1</tpAmb><chNFe>{key}</chNFe><tpEvento>110111</tpEvento>
<cStat>135</cStat></infEvento></retEvento></procEventoNFe>""".encode()


@pytest.fixture
def certificate():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA DE TESTE")])
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private.public_key())
        .serial_number(1)
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.OtherName(ObjectIdentifier("2.16.76.1.3.3"), b"\x0c\x0e" + CNPJ.encode())]
            ),
            False,
        )
        .sign(private, hashes.SHA256())
    )
