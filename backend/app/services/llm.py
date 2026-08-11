"""Abstraction over the Gemini API (chat, extraction, embeddings).

Every model call goes through here so the LLM backend is swappable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types


def _mime_from_path(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")


class LLMError(RuntimeError):
    pass


class LLMService:
    def __init__(
        self,
        api_key: str,
        chat_model: str = "gemini-2.5-flash",
        embed_model: str = "gemini-embedding-001",
        embed_dimensions: int = 768,
    ):
        self.api_key = api_key
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.embed_dimensions = embed_dimensions
        self.client = genai.Client(api_key=api_key) if api_key else None

    # -- guardrails ---------------------------------------------------------
    def require_client(self):
        if not self.client or not (self.api_key or "").strip():
            raise LLMError(
                "Gemini API key is not set. Add GEMINI_API_KEY to backend/.env "
                "(see README.md) and restart the server."
            )

    # -- chat -----------------------------------------------------------------
    def stream_chat(
        self,
        *,
        system: str | None,
        turns: list[dict[str, str]],  # [{"role": "user"|"model", "content": ...}]
        new_user_text: str,
    ) -> Any:
        """Stream a chat completion; yields text chunks."""
        self.require_client()
        contents: list[Any] = []
        for t in turns:
            role = "model" if t.get("role") == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(t["content"])])
            )
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(new_user_text)])
        )
        config = (
            types.GenerateContentConfig(system_instruction=system)
            if system
            else None
        )
        stream = self.client.models.generate_content_stream(
            model=self.chat_model, contents=contents, config=config
        )
        return stream

    # -- one-shot generation (used for memory extraction) -----------------------
    def complete_json(self, prompt: str) -> Any:
        """Ask the model to return JSON; returns the parsed object/list."""
        self.require_client()
        response = self.client.models.generate_content(
            model=self.chat_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )
        text = response.text or ""
        return _parse_json(text)

    # -- embeddings --------------------------------------------------------------
    def embed(self, texts: list[str]) -> list[list[float]]:
        self.require_client()
        if not texts:
            return []
        response = self.client.models.embed_content(
            model=self.embed_model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=self.embed_dimensions,
            ),
        )
        return [emb.values for emb in response.embeddings]

    # -- image understanding ---------------------------------------------------
    def describe_image(self, image_path: str, prompt: str | None = None) -> str:
        """Caption an image using the multimodal chat model."""
        self.require_client()
        prompt = prompt or (
            "Describe this photo in 1-2 concise sentences for a memory "
            "assistant. Mention people, objects, places, and any visible text."
        )
        response = self.client.models.generate_content(
            model=self.chat_model,
            contents=[
                prompt,
                types.Part.from_bytes(
                    data=Path(image_path).read_bytes(),
                    mime_type=_mime_from_path(image_path),
                ),
            ],
        )
        return (response.text or "").strip()


def _parse_json(text: str) -> Any:
    """Extract a JSON value from a string, tolerating code fences/junk."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Strip any leading prose up to the first [ or { (heuristic).
    start = min([i for i in (text.find("["), text.find("{")) if i != -1] or [0])
    text = text[start:]
    return json.loads(text)