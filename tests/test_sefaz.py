from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from conftest import CNPJ, make_key

from nfce_mg.certificates import Certificate
from nfce_mg.domain import NS, AppError, parse_xml
from nfce_mg.sefaz import SefazMG


def cert():
    now = datetime.now(UTC)
    return Certificate(
        "CurrentUser", "A" * 40, "TEST", CNPJ, now - timedelta(days=1), now + timedelta(days=1)
    )


@pytest.mark.parametrize(
    "environment,host,env",
    [
        ("producao", "nfce", "1"),
        ("homologacao", "hnfce", "2"),
    ],
)
def test_status_routes_and_uses_selected_certificate(environment, host, env):
    response = (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
        '<retConsStatServ xmlns="http://www.portalfiscal.inf.br/nfe">'
        "<cStat>107</cStat><xMotivo>Servico em operacao</xMotivo>"
        "</retConsStatServ></s:Body></s:Envelope>"
    )
    with patch("nfce_mg.sefaz.run_store", return_value=response) as transport:
        result = SefazMG(cert(), environment).status()
    assert result["codigo"] == "107"
    payload = transport.call_args.args[1]
    assert payload["thumbprint"] == "A" * 40
    assert payload["url"] == f"https://{host}.fazenda.mg.gov.br/nfce/services/NFeStatusServico4"
    body = parse_xml(payload["xml"].encode())
    assert body.findtext(".//n:tpAmb", namespaces=NS) == env
    assert body.findtext(".//n:cUF", namespaces=NS) == "31"


def test_consult_rejects_invalid_key_before_transport():
    with patch("nfce_mg.sefaz.run_store") as transport, pytest.raises(AppError):
        SefazMG(cert(), "producao").consult("<malicious>")
    transport.assert_not_called()


def test_consult_sends_valid_key_and_handles_soap_fault():
    with patch("nfce_mg.sefaz.run_store", return_value="<Fault/>") as transport, pytest.raises(AppError):
        SefazMG(cert(), "producao").consult(make_key())
    payload = transport.call_args.args[1]
    assert "NFeConsultaProtocolo4" in payload["url"]
    assert make_key() in payload["xml"]


def test_expired_certificate_rejected():
    now = datetime.now(UTC)
    expired = Certificate(
        "CurrentUser", "A" * 40, "TEST", CNPJ, now - timedelta(days=2), now - timedelta(days=1)
    )
    with pytest.raises(AppError):
        SefazMG(expired, "producao")
