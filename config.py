import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

__all__ = ["settings", "setup", "LOG_PATH"]

LOG_PATH = Path(__file__).parent / "bot_bridge.log"

settings = SimpleNamespace(
    telegram_user="",
    backfill_count=10,
    http_timeout=30.0,
    upload_timeout=120.0,
    heartbeat_interval=300,
    cookie_probe_interval=600,
    safety_reconcile_interval=60,
    msg_map_limit=2000,
    queued_dedup_limit=1000,
    album_wait_seconds=4.0,
    ws_backoff_initial=3,
    ws_backoff_max=60,
    user_agent="Mozilla/5.0 BridgeBot/2.0",
    ws_path="/socket.io",
    show_delete_button=True,
    tag_aliases=True,
    mirror_deletions=False,
)

_initialized = False


def _envint(key: str, default: int) -> int:
    v = os.getenv(key)
    return int(v) if v else default


def _envfloat(key: str, default: float) -> float:
    v = os.getenv(key)
    return float(v) if v else default


def _envbool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "y", "sim")


def setup() -> None:
    global _initialized
    if _initialized:
        return
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            RotatingFileHandler(str(LOG_PATH), maxBytes=5 * 1024 * 1024, backupCount=2, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    load_dotenv(dotenv_path=Path(__file__).parent / '.env')
    settings.telegram_user = os.getenv("TELEGRAM_USER", "")
    settings.backfill_count = _envint("BACKFILL_COUNT", 10)
    settings.http_timeout = _envfloat("HTTP_TIMEOUT", 30.0)
    settings.upload_timeout = _envfloat("UPLOAD_TIMEOUT", 120.0)
    settings.heartbeat_interval = _envint("HEARTBEAT_INTERVAL", 300)
    settings.cookie_probe_interval = _envint("COOKIE_PROBE_INTERVAL", 600)
    settings.safety_reconcile_interval = _envint("SAFETY_RECONCILE_INTERVAL", 60)
    settings.msg_map_limit = _envint("MSG_MAP_LIMIT", 2000)
    settings.queued_dedup_limit = _envint("QUEUED_DEDUP_LIMIT", 1000)
    settings.album_wait_seconds = _envfloat("ALBUM_WAIT_SECONDS", 4.0)
    settings.ws_backoff_initial = _envint("WS_BACKOFF_INITIAL", 3)
    settings.ws_backoff_max = _envint("WS_BACKOFF_MAX", 60)
    settings.user_agent = os.getenv("USER_AGENT", "Mozilla/5.0 BridgeBot/2.0")
    settings.ws_path = os.getenv("WS_PATH", "/socket.io")
    settings.show_delete_button = _envbool("SHOW_DELETE_BUTTON", True)
    settings.tag_aliases = _envbool("TAG_ALIASES", True)
    settings.mirror_deletions = _envbool("MIRROR_DELETIONS", False)
    _initialized = True
