"""Local LLM backend via Ollama (fully offline, no API key).

Implements the same contract as `LLMService` (Gemini) so the rest of the
memory architecture is untouched:

  - stream_chat   -> POST /v1/chat/completions (stream=true)
  - complete_json -> POST /api/chat (format=json)
  - embed         -> POST /api/embed
  - describe_image -> POST /api/generate (images=<base64>)
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from .llm import LLMError, _parse_json


class OllamaLLM:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        chat_model: str = "llama3.2:3b",
        embed_model: str = "all-minilm",
        vision_model: str = "",
        http: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.vision_model = vision_model
        self.http = http or httpx.Client(base_url=self.base_url, timeout=600)

    # -- guardrails ---------------------------------------------------------
    def _require(self):
        try:
            self.http.get("/api/tags")
        except Exception as exc:
            raise LLMError(
                f"Cannot reach Ollama at {self.base_url}. "
                f"Run `ollama serve` and pull the models first. ({exc})"
            ) from exc

    # -- chat -----------------------------------------------------------------
    def stream_chat(
        self,
        *,
        system: str | None,
        turns: list[dict[str, str]],  # [{"role": "user"|"assistant", "content": ...}]
        new_user_text: str,
    ) -> Any:
        """Stream a chat completion; yields objects with `.text`."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        for t in turns:
            role = "assistant" if t.get("role") == "assistant" else "user"
            messages.append({"role": role, "content": t["content"]})
        messages.append({"role": "user", "content": new_user_text})

        with self.http.stream(
            "POST",
            "/v1/chat/completions",
            json={"model": self.chat_model, "messages": messages, "stream": True},
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield SimpleNamespace(text=content)

    # -- one-shot JSON generation (memory extraction) ------------------------------
    def complete_json(self, prompt: str) -> Any:
        resp = self.http.post(
            "/api/chat",
            json={
                "model": self.chat_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
            },
        )
        resp.raise_for_status()
        text = resp.json().get("message", {}).get("content", "")
        return _parse_json(text)

    # -- embeddings --------------------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self.http.post(
            "/api/embed", json={"model": self.embed_model, "input": texts}
        )
        resp.raise_for_status()
        return [list(e) for e in resp.json().get("embeddings", [])]

    # -- image understanding -------------------------------------------------------
    def describe_image(self, image_path: str, prompt: str | None = None) -> str:
        """Caption an image using the configured vision model."""
        model = self.vision_model or self.chat_model
        if not self.vision_model:
            raise LLMError(
                "Ollama has no vision model configured. Set OLLAMA_VISION_MODEL in "
                "backend/.env (e.g. OLLAMA_VISION_MODEL=qwen2.5vl:3b) and run "
                f"`ollama pull qwen2.5vl:3b`, or use LLM_PROVIDER=gemini for photos."
            )
        prompt = prompt or (
            "Describe this photo in 1-2 concise sentences for a memory "
            "assistant. Mention people, objects, places, and any visible text."
        )
        data = {
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(Path(image_path).read_bytes()).decode()],
            "stream": False,
        }
        try:
            resp = self.http.post("/api/generate", json=data)
            resp.raise_for_status()
        except Exception as exc:
            raise LLMError(
                f"Vision model '{model}' failed. Is it pulled? "
                f"Try `ollama pull {model}`. ({exc})"
            ) from exc
        return (resp.json().get("response") or "").strip()
