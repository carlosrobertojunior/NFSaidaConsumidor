from .certificates import Certificate, run_store
from .domain import NS, AppError, parse_xml, validate_key


class SefazMG:
    """Consultas oficiais mTLS. Não oferece distribuição mensal de XML."""

    def __init__(self, certificate: Certificate, environment: str):
        if environment not in {"producao", "homologacao"}:
            raise AppError("Ambiente inválido.")
        certificate.check()
        self.certificate = certificate
        self.environment = environment

    def _call(self, service: str, body: str, result_tag: str) -> dict:
        self.certificate.check()
        host = "nfce" if self.environment == "producao" else "hnfce"
        soap = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body>'
            f'<nfeDadosMsg xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/{service}">'
            f"{body}</nfeDadosMsg></s:Body></s:Envelope>"
        )
        raw = run_store(
            "request",
            {
                "store": self.certificate.store,
                "thumbprint": self.certificate.thumbprint,
                "url": f"https://{host}.fazenda.mg.gov.br/nfce/services/{service}",
                "xml": soap,
            },
        )
        root = parse_xml(raw.encode("utf-8"))
        ret = root.find(f".//n:{result_tag}", NS)
        if ret is None:
            raise AppError("A SEFAZ retornou uma resposta SOAP inesperada.")
        return {"codigo": ret.findtext("n:cStat", "", NS), "motivo": ret.findtext("n:xMotivo", "", NS)}

    def status(self):
        env = "1" if self.environment == "producao" else "2"
        return self._call(
            "NFeStatusServico4",
            f'<consStatServ xmlns="{NS["n"]}" versao="4.00"><tpAmb>{env}</tpAmb>'
            "<cUF>31</cUF><xServ>STATUS</xServ></consStatServ>",
            "retConsStatServ",
        )

    def consult(self, key: str):
        validate_key(key, self.certificate.cnpj)
        env = "1" if self.environment == "producao" else "2"
        return self._call(
            "NFeConsultaProtocolo4",
            f'<consSitNFe xmlns="{NS["n"]}" versao="4.00"><tpAmb>{env}</tpAmb>'
            f"<xServ>CONSULTAR</xServ><chNFe>{key}</chNFe></consSitNFe>",
            "retConsSitNFe",
        )
