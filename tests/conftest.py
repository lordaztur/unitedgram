import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("BASE_URL", "https://example.test")
os.environ.setdefault("WS_HOST", "https://example.test")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "stub")
os.environ.setdefault("TELEGRAM_CHAT_ID", "-1")
os.environ.setdefault("USER_ID", "1")
os.environ.setdefault("CSRF_TOKEN", "stub")
os.environ.setdefault("COOKIE", "stub")
