import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory of the Project
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")


class Config:
    """Application configuration loaded from environment variables."""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-default")
    DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
    PORT = int(os.getenv("PORT", 5000))

    # Database Settings
    db_path = BASE_DIR / "restaurant.db"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URI", f"sqlite:///{db_path.as_posix()}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # OpenRouter Configuration
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    # Primary free model — must end with :free. Default: NVIDIA Nemotron 3.5 Lightning (free).
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free")
    # Comma-separated fallback free models (all must end with :free). Used when primary is rate-limited/quota-exhausted.
    OPENROUTER_FALLBACK_MODELS = os.getenv(
        "OPENROUTER_FALLBACK_MODELS",
        "nvidia/nemotron-3.5-lightning:free,nvidia/nemotron-3-super-120b-a12b:free,poolside/laguna-xs-2.1:free,cohere/north-mini-code:free,z-ai/glm-5.2:free",
    )
    # ---------------------------------------------------------------------------
    # Free-model validation helpers — used by agent.py fallback logic.
    # Every model in the primary + fallback chain MUST end with ":free".
    # No paid model, no Google model, no non-free model can be auto-selected.
    # ---------------------------------------------------------------------------

    @staticmethod
    def is_model_free(model_id: str) -> bool:
        """Return True only if the model ID ends with ':free' (OpenRouter free tier)."""
        if not model_id:
            return False
        return model_id.strip().endswith(":free")

    @staticmethod
    def get_fallback_models() -> list[str]:
        """Parse OPENROUTER_FALLBACK_MODELS into a de-duplicated list of free models.

        Skips any entry that does not end with ':free', is empty, or is a Google model.
        The primary model is excluded from the fallback list to avoid self-retry.
        """
        raw = getattr(config, "OPENROUTER_FALLBACK_MODELS", "") or ""
        seen: set[str] = set()
        result: list[str] = []
        primary = getattr(config, "OPENROUTER_MODEL", "") or ""
        for entry in raw.split(","):
            m = entry.strip()
            if not m:
                continue
            # Free-model gate — only :free models are eligible.
            if not config.is_model_free(m):
                continue
            # Skip Google models (no Google API key / Google credits dependency).
            if m.lower().startswith("google/"):
                continue
            # Skip the primary model itself (avoid retrying the same exhausted model).
            if m == primary:
                continue
            if m not in seen:
                seen.add(m)
                result.append(m)
        return result

    # ChromaDB Vector Store Path
    CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "data" / "chroma_db"))

    # Agent defaults for future LangGraph/LLM usage
    AGENT_TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0.3"))
    AGENT_MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", "512"))


# Active configuration instance
config = Config()
