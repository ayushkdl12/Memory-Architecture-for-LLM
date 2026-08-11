from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Universal Memory Architecture"
    debug: bool = True

    # --- LLM (Gemini) ---
    gemini_api_key: str = ""
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dimensions: int = 768

    # --- Vision (photo understanding) ---
    # "gemini" -> use Gemini for photos even when chat runs locally via Ollama.
    # ""       -> same provider as LLM_PROVIDER (Gemini chat model is multimodal).
    vision_provider: str = "gemini"
    gemini_vision_model: str = "gemini-2.5-flash"

    # --- LLM (local Ollama) ---
    llm_provider: str = "ollama"          # "ollama" (default) | "gemini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2:3b"
    ollama_embed_model: str = "all-minilm"
    ollama_vision_model: str = ""         # e.g. "qwen2.5vl:3b"; empty -> no vision on ollama

    # --- Media / photo uploads ---
    media_dir: str = str(BASE_DIR / "uploads")
    media_max_bytes: int = 8 * 1024 * 1024   # 8 MB per image

    # --- Web search (ChatGPT-search / Claude-web-search analogue) ---
    search_provider: str = "duckduckgo"   # "duckduckgo" (no key) | "tavily" (key)
    tavily_api_key: str = ""
    web_search_enabled: bool = True
    web_search_max_results: int = 5
    web_search_char_budget: int = 1200

    # --- Documents (file upload & analysis) ---
    document_max_bytes: int = 16 * 1024 * 1024   # 16 MB per file
    document_chunk_size: int = 800
    document_chunk_overlap: int = 80

    # --- Database ---
    database_url: str = (
        "postgresql+psycopg2://memory:memory_pass@localhost:5432/memory_db"
    )

    # --- Vector store ---
    vector_store_provider: str = "numpy"  # "numpy" | "chroma"
    vector_store_dir: str = str(BASE_DIR / ".vectorstore")

    # --- Memory pipeline ---
    default_user_id: str = "00000000-0000-0000-0000-000000000001"  # demo user UUID
    default_session_title: str = "New chat"
    retrieval_top_k: int = 8                     # candidates from semantic search
    retrieval_min_score: float = 0.12            # cosine threshold (all-minilm scores run low; 0.35 was too strict)
    context_max_atoms: int = 6                   # atoms injected into the prompt
    context_char_budget: int = 1200              # max chars for the memory block
    retention_event_threshold_days: int = 30     # EVENT atoms older than this are archived
    confidence_auto_commit: float = 0.6          # atoms >= this confidence are auto-confirmed
    importance_weights: dict = {                 # Score = a*I + b*R + g*F + d*U
        "alpha": 0.4,
        "beta": 0.3,
        "gamma": 0.2,
        "delta": 0.1,
    }
    retention_score_threshold: float = 0.25      # atoms below tau get archived

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
