"""
Minimal Ollama /api/chat client (standard library only), used for judge calls.

Works in any of the project venvs, so the SRS Agent side (SRSAgent/.venv) and
the verifier side (SRS_to_code_traceability/.venv) share one implementation.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class OllamaChat:
    def __init__(self, model: str, host: str = "http://localhost:11434", *,
                 temperature: float = 0.1, max_tokens: int = 1024, seed: int = 42,
                 timeout_s: int = 600, think: Optional[bool] = None, retries: int = 2):
        self.model = model
        self.url = host.rstrip("/") + "/api/chat"
        self.options = {"temperature": temperature, "num_predict": max_tokens, "seed": seed,
                        "num_ctx": 8192}
        self.timeout_s = timeout_s
        self.think = think
        self.retries = retries

    @classmethod
    def from_config(cls, model_entry: Dict[str, Any], ollama_cfg: Dict[str, Any]) -> "OllamaChat":
        return cls(model_entry["ollama_model"], ollama_cfg.get("host", "http://localhost:11434"),
                   temperature=ollama_cfg.get("temperature", 0.1),
                   max_tokens=ollama_cfg.get("max_tokens", 1024),
                   seed=ollama_cfg.get("seed", 42), timeout_s=ollama_cfg.get("timeout_s", 600),
                   think=model_entry.get("think"))

    def chat(self, system: str, user: str) -> str:
        body: Dict[str, Any] = {
            "model": self.model, "stream": False, "options": self.options,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.think is not None:
            body["think"] = self.think
        data = json.dumps(body).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(self.url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read())["message"]["content"]
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise RuntimeError(f"Ollama has no model {self.model!r}") from exc
                last = exc
            except Exception as exc:  # timeouts, connection resets
                last = exc
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{self.model} failed after {self.retries + 1} attempts: {last}")
