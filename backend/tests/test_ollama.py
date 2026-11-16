import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tracelight.orchestrator.ollama import (OllamaUnavailable, check_models, has_model, list_models,
                                            model_details, server_version)


@pytest.fixture()
def fake_ollama():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = {"/api/tags": {"models": [{"name": "llama3.1:latest", "size": 4920753328},
                                             {"name": "qwen2.5-coder:7b", "size": 4683087332}]},
                    "/api/version": {"version": "0.12.3"}}.get(self.path)
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write(json.dumps(body or {}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_models_sizes_and_version(fake_ollama):
    assert list_models(fake_ollama) == ["llama3.1:latest", "qwen2.5-coder:7b"]
    assert model_details(fake_ollama)[0] == {"name": "llama3.1:latest", "size": 4920753328}
    assert server_version(fake_ollama) == "0.12.3"
    assert check_models(fake_ollama, {"srs": "llama3.1", "verifier": "qwen2.5-coder:14b"}) == {"srs": True, "verifier": False}


def test_has_model_tags():
    assert has_model("llama3.1", ["llama3.1:latest"])
    assert not has_model("llama3.1:8b", ["llama3.1:latest"])


def test_unreachable():
    with pytest.raises(OllamaUnavailable):
        list_models("http://127.0.0.1:9", timeout=0.5)
    assert server_version("http://127.0.0.1:9", timeout=0.5) is None
