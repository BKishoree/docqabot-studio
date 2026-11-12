"""Environment variables -> typed settings (DESIGN 5.3).

Read at call time, never cached at import, so tests can change the environment.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_STUB_URL = "http://openai-stub:8001/v1"
# Local developer default only (loopback DB container from compose / `docqabot-dev-db`).
# compose.yaml always passes its own DATABASE_URL.
DEFAULT_DATABASE_URL = (
    "postgresql://docqabot:docqabot_local@127.0.0.1:5433/docqabot"
    "?connect_timeout=5&options=-c%20ivfflat.probes%3D100"
)

ALLOWED_EXTENSIONS = (".pdf", ".md", ".txt")
MAX_QUESTION_CHARS = 2000
MAX_TITLE_CHARS = 120
MAX_FILENAME_CHARS = 200
EMBEDDING_MODEL = "text-embedding-3-small"  # informational, mirrors app/embeddings.py
CHAT_MODEL = "gpt-4o-mini"  # informational, mirrors app/rag.py
RETRIEVAL_TOP_K = 5  # mirrors app.rag.retrieve_context defaults
RETRIEVAL_MIN_SIMILARITY = 0.3


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(raw.strip()))
    except ValueError:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, float(raw.strip()))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    stub_url: str
    bind_addr: str
    auth_user: str
    auth_password: str
    max_upload_mb: float
    openai_timeout_s: float
    openai_max_retries: int
    db_startup_retries: int
    web_dist: Path
    log_level: str

    @property
    def auth_enabled(self) -> bool:
        return bool(self.auth_user) and bool(self.auth_password)

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def bind_is_loopback(self) -> bool:
        addr = self.bind_addr.strip().strip("[]")
        if addr.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(addr).is_loopback
        except ValueError:
            return False

    @property
    def mode(self) -> str:
        return "demo" if self.demo_mode else "live"


def load_settings() -> Settings:
    web_dist = Path(os.environ.get("STUDIO_WEB_DIST") or "web/dist")
    if not web_dist.is_absolute():
        web_dist = PROJECT_ROOT / web_dist
    return Settings(
        demo_mode=env_bool("STUDIO_DEMO_MODE"),
        stub_url=(os.environ.get("STUDIO_STUB_URL") or DEFAULT_STUB_URL).strip(),
        bind_addr=(os.environ.get("STUDIO_BIND_ADDR") or "127.0.0.1").strip(),
        auth_user=os.environ.get("STUDIO_AUTH_USER") or "",
        auth_password=os.environ.get("STUDIO_AUTH_PASSWORD") or "",
        max_upload_mb=_env_float("STUDIO_MAX_UPLOAD_MB", 20.0, minimum=0.001),
        openai_timeout_s=_env_float("STUDIO_OPENAI_TIMEOUT_S", 60.0, minimum=1.0),
        openai_max_retries=_env_int("STUDIO_OPENAI_MAX_RETRIES", 1),
        db_startup_retries=_env_int("STUDIO_DB_STARTUP_RETRIES", 30, minimum=1),
        web_dist=web_dist,
        log_level=(os.environ.get("STUDIO_LOG_LEVEL") or "INFO").strip().upper(),
    )
