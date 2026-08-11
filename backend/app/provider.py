"""Shared service singletons (LLM, vector store). Lazily initialized so the
app and tests can construct them independently.

LLM backend is configurable: `LLM_PROVIDER=ollama` (default, fully local) or
`LLM_PROVIDER=gemini` (requires GEMINI_API_KEY).
"""
from __future__ import annotations

from .config import settings
from .services.llm import LLMService
from .vectorstore import build_vector_store

_llm = None
_vector_store = None


def get_llm():
    global _llm
    if _llm is None:
        if settings.llm_provider.lower() == "gemini":
            _llm = LLMService(
                api_key=settings.gemini_api_key,
                chat_model=settings.gemini_chat_model,
                embed_model=settings.gemini_embed_model,
                embed_dimensions=settings.embed_dimensions,
            )
        else:
            from .services.ollama import OllamaLLM

            _llm = OllamaLLM(
                base_url=settings.ollama_base_url,
                chat_model=settings.ollama_chat_model,
                embed_model=settings.ollama_embed_model,
                vision_model=settings.ollama_vision_model,
            )
    return _llm


def get_llm_name() -> str:
    """Human-readable active provider + model (for /health)."""
    llm = get_llm()
    return f"{settings.llm_provider}/{getattr(llm, 'chat_model', '?')}"


def get_vision_llm():
    """LLM used for photo understanding.

    `vision_provider=gemini` (default) gives vision through Gemini even when
    chat stays fully local via Ollama; an empty value falls back to the main
    provider (Gemini's chat model is multimodal anyway).
    """
    if settings.vision_provider.lower() == "gemini":
        return LLMService(
            api_key=settings.gemini_api_key,
            chat_model=settings.gemini_vision_model,
            embed_model=settings.gemini_embed_model,
            embed_dimensions=settings.embed_dimensions,
        )
    return get_llm()


def get_vector_store():
    global _vector_store
    if _vector_store is None:
        _vector_store = build_vector_store(
            settings.vector_store_provider,
            settings.vector_store_dir,
            get_llm(),
        )
    return _vector_store


def get_search_service():
    from .services.websearch import SearchService

    return SearchService(
        provider=settings.search_provider,
        tavily_api_key=settings.tavily_api_key,
        max_results=settings.web_search_max_results,
        char_budget=settings.web_search_char_budget,
    )
