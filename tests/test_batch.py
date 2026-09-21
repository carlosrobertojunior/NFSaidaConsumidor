import json
import threading
from pathlib import Path
from zipfile import ZipFile

from conftest import CNPJ, make_event, make_key, make_xml

from nfce_mg.batch import Batch
from nfce_mg.domain import AppError, Month


class FakeClient:
    base = "https://test.invalid"

    def __init__(self, rows=None, broken=False):
        self.calls = []
        self.broken = broken
        self.rows = (
            rows
            if rows is not None
            else [
                {
                    "id": "test",
                    "modelo": 65,
                    "chave": make_key(),
                    "status": "cancelado",
                    "data_emissao": "2026-08-31T23:59:59-03:00",
                }
            ]
        )

    def list_invoices(self, cnpj, environment):
        yield from self.rows

    def xml(self, invoice_id, cancellation=False):
        self.calls.append((invoice_id, cancellation))
        if cancellation and self.broken:
            raise AppError("Evento indisponível")
        return make_event() if cancellation else make_xml()


def test_batch_download_event_zip_and_resume(tmp_path):
    client = FakeClient()
    result = Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    assert result["resultado"] == "concluido"
    assert result["xmls"] == 1
    assert len(client.calls) == 2
    with ZipFile(result["arquivo_zip"]) as archive:
        assert f"xml/{make_key()}-nfe.xml" in archive.namelist()
        assert f"eventos/{make_key()}-cancelamento.xml" in archive.namelist()
    client.calls.clear()
    resumed = Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    assert resumed["xmls"] == 1
    assert client.calls == []


def test_event_failure_is_partial_and_resumed(tmp_path):
    client = FakeClient(broken=True)
    result = Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    assert result["resultado"] == "parcial"
    assert len(result["erros"]) == 1
    client.broken = False
    client.calls.clear()
    result = Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    assert result["resultado"] == "concluido"
    assert client.calls == [("test", True)]


def test_empty_result_does_not_zip_stale_xmls(tmp_path):
    Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(FakeClient())
    result = Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(FakeClient([]))
    with ZipFile(result["arquivo_zip"]) as archive:
        assert not any(name.endswith(".xml") for name in archive.namelist())
    assert result["xmls"] == 0


def test_filter_uses_issue_date_not_created_date(tmp_path):
    client = FakeClient()
    client.rows[0]["created_at"] = "2026-09-10T00:00:00Z"
    assert Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)["xmls"] == 1
    client.calls.clear()
    assert Batch(tmp_path, CNPJ, Month(2026, 9)).from_acbr(client)["xmls"] == 0
    assert client.calls == []


def test_invalid_api_xml_is_not_saved(tmp_path):
    client = FakeClient()
    client.xml = lambda *_: b"<html>error</html>"
    result = Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    assert result["resultado"] == "parcial"
    assert result["xmls"] == 0
    assert list(tmp_path.rglob("*.xml")) == []


def test_cancel_produces_partial_report(tmp_path):
    stop = threading.Event()
    stop.set()
    result = Batch(tmp_path, CNPJ, Month(2026, 8), stop=stop).from_acbr(FakeClient())
    assert result["interrompido"]
    assert result["resultado"] == "parcial"


def test_local_folder_filters_month_and_imports_events(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "note.XML").write_bytes(make_xml())
    (source / "cancel.xml").write_bytes(make_event())
    (source / "other.xml").write_bytes(make_xml(date="2026-07-01T00:00:00-03:00"))
    result = Batch(tmp_path / "out", CNPJ, Month(2026, 8)).from_folder(source)
    assert result["xmls"] == 1
    assert result["documentos"][0]["status_origem"] == "cancelado (evento local)"
    report = json.loads(Path(result["relatorio"]).read_text(encoding="utf-8"))
    assert report["cnpj"] == CNPJ


def test_corrupt_cache_removed_for_next_retry(tmp_path):
    client = FakeClient()
    Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    for path in tmp_path.rglob(".cache/*.xml"):
        path.write_bytes(b"corrupt")
    result = Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    assert result["resultado"] == "parcial"
    # Primeiro retoma a nota e depois detecta o evento também corrompido.
    Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)
    assert Batch(tmp_path, CNPJ, Month(2026, 8)).from_acbr(client)["resultado"] == "concluido"
