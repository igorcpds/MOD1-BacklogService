"""Owner wire contract observed with our synthetic review; no external calls."""

import base64
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from pydantic import ValidationError

from backlog_service.module4_client import Module4Client, trusted_base_url
from backlog_service.module4_domain import Module4Draft

BASE = "https://revisor-codigo-ia-gio-ach9dbg3g9ekazf3.chilecentral-01.azurewebsites.net"
PASSWORD = "synthetic-private-password-never-a-real-credential"
BODY = {
    "id": "900eace0-6580-43c9-a6ae-594b6953a1e5",
    "criado_em": "2026-11-16T06:41:59.322445+00:00",
    "arquitetura": "multicamadas",
    "arquivos": 1,
    "achados": [
        {
            "arquivo": "Conjunto analisado",
            "linha": None,
            "categoria": "Testes",
            "gravidade": "Média",
            "titulo": "Nenhum arquivo de teste identificado",
            "sugestao": "Inclua arquivos de teste na revisão.",
        }
    ],
    "testes": [],
    "testes_executados": False,
    "pr": None,
    "ia": {"status": "Não solicitada", "texto": "Apenas análise estática."},
    "markdown": "# Revisão de código\n\nSem execução de testes.",
}


def draft(**changes):
    return Module4Draft.model_validate(
        {
            "arquivos": [
                {"caminho": "exemplo.py", "conteudo": "def dobro(x):\n    return x * 2\n"}
            ],
            "arquitetura": "multicamadas",
            "usar_ia": False,
            **changes,
        }
    )


def client(handler):
    return Module4Client(BASE, "revisor", PASSWORD, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("status", [200, 201])
def test_real_success_status_and_basic_only_wire_contract(status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=BODY)

    result = client(respond).analyze(draft())
    assert result.status == "succeeded" and result.http_status == status
    assert result.review.id == BODY["id"] and result.review.testes_executados is False
    assert result.review.ia.status == "Não solicitada"
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == BASE + "/api/analisar" and request.method == "POST"
    assert (
        request.headers["Authorization"]
        == "Basic " + base64.b64encode(("revisor:" + PASSWORD).encode()).decode()
    )
    assert "cookie" not in request.headers
    payload = json.loads(request.content)
    assert payload == draft().model_dump(mode="json", exclude_none=True)
    assert PASSWORD not in request.content.decode() and "Bearer" not in request.content.decode()


@pytest.mark.parametrize(
    "status,outcome",
    [
        (301, "failed"),
        (400, "failed"),
        (401, "blocked"),
        (403, "blocked"),
        (429, "blocked"),
        (500, "uncertain"),
        (503, "uncertain"),
        (202, "uncertain"),
    ],
)
def test_no_redirect_no_retry_and_sanitized_failures(status, outcome):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            json={"secret": PASSWORD},
            headers={"location": "https://untrusted.invalid/steal"},
        )

    result = client(respond).analyze(draft())
    assert result.status == outcome and result.review is None
    assert result.http_status == status and len(calls) == 1
    assert PASSWORD not in repr(result) and "secret" not in (result.error or "")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {**BODY, "arquivos": True},
        {**BODY, "testes_executados": "false"},
        {**BODY, "id": "not-a-review-id"},
    ],
)
def test_malformed_created_response_is_uncertain_and_never_an_approval(body):
    result = client(lambda request: httpx.Response(201, json=body)).analyze(draft())
    assert result.status == "uncertain" and result.review is None


def test_oversize_non_json_and_read_timeout_are_uncertain():
    for response in [
        httpx.Response(201, content=b"x" * 1048577),
        httpx.Response(201, content=b"not json"),
    ]:
        result = client(lambda request: response).analyze(draft())
        assert result.status == "uncertain" and result.review is None

    def timeout(request):
        raise httpx.ReadTimeout(PASSWORD, request=request)

    result = client(timeout).analyze(draft())
    assert result.status == "uncertain" and PASSWORD not in repr(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"arquivos": []},
        {"arquivos": [{"caminho": "bad.js", "conteudo": "x"}]},
        {"arquivos": [{"caminho": "../private.py", "conteudo": "x"}]},
        {"arquivos": [{"caminho": "a.py", "conteudo": "á" * 50001}]},
        {"arquivos": [{"caminho": f"a{i}.py", "conteudo": "x"} for i in range(21)]},
        {"pr_url": "https://github.com/owner/repo/pull/1"},
        {"arquivos": None, "pr_url": "http://127.0.0.1/private"},
        {"usar_ia": "true"},
        {"arquitetura": "unknown"},
    ],
)
def test_input_limits_and_exactly_one_authorized_source(changes):
    with pytest.raises(ValidationError):
        draft(**changes)


def test_valid_pr_has_no_file_payload_and_preserves_explicit_ai_choice():
    model = draft(arquivos=None, pr_url="https://github.com/owner/repo/pull/1", usar_ia=True)
    assert model.model_dump(mode="json", exclude_none=True) == {
        "pr_url": "https://github.com/owner/repo/pull/1",
        "arquitetura": "multicamadas",
        "usar_ia": True,
    }


def test_nonfinite_provider_values_are_not_accepted_for_json_persistence():
    body = {**BODY, "testes": [float("nan")]}
    result = client(lambda request: httpx.Response(201, content=json.dumps(body))).analyze(draft())
    assert result.status == "uncertain" and result.review is None


@pytest.mark.parametrize("field", ["testes", "pr"])
def test_overflowed_nested_json_numbers_are_not_successful_reviews(field):
    content = json.dumps(BODY)
    if field == "testes":
        content = content.replace('"testes": []', '"testes": [{"nested": [1e400]}]')
    else:
        content = content.replace('"pr": null', '"pr": {"nested": [-1e400]}')
    result = client(lambda request: httpx.Response(201, content=content)).analyze(draft())
    assert result.status == "uncertain" and result.review is None


@contextmanager
def owner_server(delay=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append((self.path, dict(self.headers), json.loads(data)))
            time.sleep(delay)
            body = json.dumps(BODY).encode()
            try:
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_actual_http_serialization_ignores_environment_proxies(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with owner_server() as (url, requests):
        result = Module4Client(url, "revisor", PASSWORD).analyze(draft())
        assert result.status == "succeeded" and len(requests) == 1
        path, headers, payload = requests[0]
        assert path == "/api/analisar"
        assert headers["Authorization"].startswith("Basic ") and "Cookie" not in headers
        assert payload == draft().model_dump(mode="json", exclude_none=True)


def test_actual_http_total_deadline_does_not_retry_an_ambiguous_post():
    with owner_server(delay=1) as (url, requests):
        started = time.monotonic()
        result = Module4Client(url, "revisor", PASSWORD, timeout=0.4).analyze(draft())
        elapsed = time.monotonic() - started
        assert result.status == "uncertain" and result.error == "delivery_uncertain"
        assert elapsed < 0.9 and len(requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://untrusted.invalid",
        BASE + "/redirect",
        BASE + "?q=x",
        "https://user:password@revisor-codigo-ia-gio-ach9dbg3g9ekazf3.chilecentral-01.azurewebsites.net",
        "https://revisor-codigo-ia-gio-ach9dbg3g9ekazf3.chilecentral-01.azurewebsites.net.evil.invalid",
    ],
)
def test_credentials_only_go_to_owner_or_explicit_loopback_test_server(url):
    with pytest.raises(ValueError):
        trusted_base_url(url)
    assert trusted_base_url(BASE + "/") == BASE
    assert trusted_base_url("http://127.0.0.1:54321") == "http://127.0.0.1:54321"
