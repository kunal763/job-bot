"""Configuration management for Job Bot."""

import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_PATH = DATA_DIR / "job_bot.db"
DEFAULT_PROFILE_PATH = BASE_DIR / "profile.json"
DEFAULT_BROWSER_DIR = DATA_DIR / "browser_context"
DEFAULT_BROWSER_DIR.mkdir(parents=True, exist_ok=True)


class BotConfig(BaseModel):
    """Runtime bot settings."""
    min_salary_lpa: float = Field(default=12.0, description="Minimum salary threshold in Lakhs Per Annum (LPA)")
    allow_unlisted_salary: bool = Field(default=False, description="Whether to consider jobs without explicit salary listed")
    default_currency: str = Field(default="INR", description="Default currency code")
    db_path: Path = Field(default=DEFAULT_DB_PATH, description="Path to SQLite database")
    profile_path: Path = Field(default=DEFAULT_PROFILE_PATH, description="Path to user profile JSON")
    browser_context_dir: Path = Field(default=DEFAULT_BROWSER_DIR, description="Persistent browser session directory")
    headless: bool = Field(default=False, description="Run browser in headless mode")
    slow_mo_ms: int = Field(default=250, description="Delay between browser actions for human-like behavior")
    
    # LLM Settings
    groq_api_key: str | None = Field(default_factory=lambda: os.getenv("GROQ_API_KEY"))
    gemini_api_key: str | None = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    groq_model: str = Field(default_factory=lambda: os.getenv("GROQ_MODEL") or "qwen/qwen3.8-27b")
    gemini_model: str = Field(default="gemini-2.5-flash")

    # Real Chrome / Session integration
    cdp_url: str | None = Field(default_factory=lambda: os.getenv("CDP_URL"))
    linkedin_cookie: str | None = Field(default_factory=lambda: os.getenv("LINKEDIN_COOKIE"))

    # Telegram Bot Settings
    telegram_bot_token: str | None = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str | None = Field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID"))


config = BotConfig()
