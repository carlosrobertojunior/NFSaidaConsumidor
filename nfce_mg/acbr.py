import time
from urllib.parse import quote

import requests

from .domain import MAX_XML, AppError

TOKEN_URL = "https://auth.acbr.api.br/realms/ACBrAPI/protocol/openid-connect/token"
BASES = {"producao": "https://prod.acbr.api.br", "sandbox": "https://hom.acbr.api.br"}


class AcbrClient:
    def __init__(self, client_id: str, client_secret: str, api_environment="producao", *, session=None):
        if not client_id or not client_secret:
            raise AppError("Informe Client ID e Client Secret da ACBr API.")
        if api_environment not in BASES:
            raise AppError("Ambiente da API inválido.")
        self.base = BASES[api_environment]
        self.client_id, self.client_secret = client_id, client_secret
        self.session = session or requests.Session()
        self.token, self.expires = "", 0.0

    def close(self):
        self.session.close()
        self.token, self.client_secret = "", ""

    def _token(self):
        if self.token and time.monotonic() < self.expires:
            return self.token
        try:
            with self.session.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "scope": "nfce",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=(10, 45),
                allow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise AppError(f"Autenticação ACBr recusada (HTTP {response.status_code}).")
                data = response.json()
                self.token = data["access_token"]
                self.expires = time.monotonic() + max(0, int(data["expires_in"]) - 60)
                return self.token
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise AppError("Falha de conexão ou resposta inválida na autenticação ACBr.") from exc

    def get(self, path: str, params=None, *, xml=False):
        refreshed = False
        for attempt in range(4):
            try:
                with self.session.get(
                    self.base + path,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._token()}",
                        "Accept": "application/xml" if xml else "application/json",
                    },
                    timeout=(10, 60),
                    allow_redirects=False,
                    stream=True,
                ) as response:
                    code = response.status_code
                    if code == 401 and not refreshed:
                        self.token, refreshed = "", True
                        continue
                    if code == 429 or 500 <= code <= 599:
                        if attempt == 3:
                            raise AppError(f"ACBr indisponível ou limite de requisições (HTTP {code}).")
                        retry = response.headers.get("Retry-After", "")
                        if retry.isdigit() and int(retry) > 60:
                            raise AppError(f"Limite ACBr: aguarde {retry} segundos e execute novamente.")
                        time.sleep(max(2**attempt, int(retry) if retry.isdigit() else 0))
                        continue
                    if code != 200:
                        raise AppError(
                            f"Consulta ACBr recusada (HTTP {code}). Verifique credenciais, plano e documento."
                        )
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > MAX_XML:
                            raise AppError("Resposta ACBr excede 10 MB.")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    if xml:
                        return content
                    import json

                    return json.loads(content)
            except requests.RequestException as exc:
                # Sem repetir um download cujo consumo pode já ter sido contabilizado.
                raise AppError(
                    "Falha de rede ao consultar ACBr. Execute novamente para retomar o lote."
                ) from exc
            except ValueError as exc:
                raise AppError("ACBr retornou JSON inválido.") from exc
        raise AppError("Não foi possível concluir a consulta ACBr.")

    def list_invoices(self, cnpj: str, environment: str):
        # O contrato não oferece data_inicial/data_final: filtrar data_emissao localmente.
        # created_at não pode ser usado para parar a paginação por competência.
        seen = set()
        skip = 0
        while True:
            page = self.get("/nfce", {"cpf_cnpj": cnpj, "ambiente": environment, "$top": 100, "$skip": skip})
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise AppError("Listagem ACBr fora do contrato esperado.")
            rows = page["data"]
            if not rows:
                break
            new = 0
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                    raise AppError("Documento ACBr sem identificador válido.")
                if row["id"] not in seen:
                    new += 1
                    seen.add(row["id"])
                    yield row
            if not new:
                raise AppError("Paginação ACBr repetida; lote interrompido para evitar resultado incompleto.")
            skip += len(rows)

    def xml(self, invoice_id: str, cancellation=False):
        suffix = "/cancelamento/xml" if cancellation else "/xml"
        return self.get("/nfce/" + quote(invoice_id, safe="") + suffix, xml=True)
