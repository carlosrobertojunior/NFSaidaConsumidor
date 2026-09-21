from unittest.mock import Mock, patch

import pytest

from nfce_mg.acbr import TOKEN_URL, AcbrClient
from nfce_mg.domain import AppError


def response(status, content=b"", payload=None, headers=None):
    result = Mock()
    result.status_code = status
    result.json.return_value = payload
    result.iter_content.return_value = [content]
    result.headers = headers or {}
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def test_auth_parameters_and_token_reuse():
    session = Mock()
    session.post.return_value = response(200, payload={"access_token": "secret-token", "expires_in": 3600})
    session.get.side_effect = [response(200, b'{"data": []}'), response(200, b"<nfeProc/>")]
    client = AcbrClient("id", "secret", session=session)
    assert list(client.list_invoices("11222333000181", "producao")) == []
    assert client.xml("id/with/slash") == b"<nfeProc/>"
    session.post.assert_called_once()
    assert session.post.call_args.args[0] == TOKEN_URL
    assert session.post.call_args.kwargs["data"]["scope"] == "nfce"
    assert session.get.call_args.args[0].endswith("/nfce/id%2Fwith%2Fslash/xml")
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_pagination_visits_all_records_even_with_short_page():
    client = AcbrClient("id", "secret")
    client.get = Mock(
        side_effect=[{"data": [{"id": "1"}, {"id": "2"}]}, {"data": [{"id": "2"}, {"id": "3"}]}, {"data": []}]
    )
    assert [r["id"] for r in client.list_invoices("cnpj", "producao")] == ["1", "2", "3"]
    assert client.get.call_args_list[1].args[1]["$skip"] == 2


def test_repeated_page_fails_instead_of_silently_truncating():
    client = AcbrClient("id", "secret")
    client.get = Mock(return_value={"data": [{"id": "1"}]})
    with pytest.raises(AppError, match="Paginação"):
        list(client.list_invoices("cnpj", "producao"))


def test_rate_limit_retries_and_401_renews():
    session = Mock()
    session.post.return_value = response(200, payload={"access_token": "token", "expires_in": 3600})
    session.get.side_effect = [
        response(429, headers={"Retry-After": "1"}),
        response(401),
        response(200, b"ok"),
    ]
    with patch("nfce_mg.acbr.time.sleep") as sleep:
        assert AcbrClient("id", "secret", session=session).xml("test") == b"ok"
    sleep.assert_called_once()
    assert session.post.call_count == 2


def test_error_message_does_not_include_remote_secrets():
    session = Mock()
    session.post.return_value = response(403, b"secret-token private-data")
    with pytest.raises(AppError) as caught:
        AcbrClient("id", "secret", session=session).xml("test")
    assert "secret" not in str(caught.value)
