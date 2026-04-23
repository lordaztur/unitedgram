import asyncio
import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from config import settings
from formatting import build_bbcode_payload

logger = logging.getLogger(__name__)

__all__ = [
    "ChatBridge",
    "BridgeConfig",
    "REQUIRED_ENV",
    "clean_html",
    "extract_reply_content",
]

REQUIRED_ENV = ("BASE_URL", "WS_HOST", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "USER_ID", "CSRF_TOKEN", "COOKIE")

HTML_PARSER = "lxml"

_RE_QUOTE_QUOTING = re.compile(
    r'^[“" ]*(?:Quoting|Citando)\s*@?([^\n:]+)(?::|\r?\n)\s*(.*)',
    re.IGNORECASE | re.DOTALL,
)
_RE_QUOTE_SHORT = re.compile(r'^@?([^\n:]{1,50})(?::|\r?\n)\s*(.*)', re.DOTALL)
_RE_MULTI_BLANK = re.compile(r'\n{3,}')
_RE_QUOTE_TOKEN = re.compile(r'(\[quote=[^\]]+\]|\[/quote\])', re.IGNORECASE)
_RE_REPLY_BBCODE = re.compile(
    r'\[quote=@?[^\]]+\](.*?)\[/quote\](?:\s*(.*))?',
    re.DOTALL | re.IGNORECASE,
)
_RE_REPLY_BB_QUOTE = re.compile(
    r'\[b\]\[url=[^\]]+\][^\[]+\[/url\]\s*:\s*\[/b\]\[color=[^\]]+\]\s*'
    r'["“”]?\[i\](.*?)\[/i\]["“”]?\s*\[/color\](?:\s*(.*))?',
    re.DOTALL | re.IGNORECASE,
)
_RE_REPLY_QUOTING = re.compile(
    r'^[“" ]*(?:Quoting|Citando)\s*@?[^:]+:\s*(.*)',
    re.DOTALL | re.IGNORECASE,
)
_RE_REPLY_OLD = re.compile(
    r'^\s*@?(?:[A-Za-z0-9_.-]+)\s*:\s*[“"].*?[”"]\s*(?:\r?\n\s*)+(.*)$',
    re.DOTALL,
)
_RE_BLANKLINE_SPLIT = re.compile(r'\n{2,}')
_RE_WS_HOST_PORT = re.compile(r'^(https?://[^:/]+)(?::\d+)?(/.*)?$')


def _compose_ws_host(host: str, port: Optional[str]) -> str:
    if not port:
        return host
    m = _RE_WS_HOST_PORT.match(host)
    if not m:
        return host
    return f"{m.group(1)}:{port}{m.group(2) or ''}"


def _log_http_failure(ctx: str, exc: Exception) -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        level = logger.error if code in (401, 403, 419) else logger.warning
        level(f"{ctx}: HTTP {code}")
    elif isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        logger.warning(f"{ctx}: rede ({type(exc).__name__}: {exc})")
    else:
        logger.warning(f"{ctx}: {type(exc).__name__}: {exc}")


def _has_quote_class(node) -> bool:
    c = node.get('class', [])
    if isinstance(c, list):
        return any('quote' in str(x).lower() for x in c)
    return isinstance(c, str) and 'quote' in c.lower()


def _is_nested_in_quote(node) -> bool:
    p = node.parent
    while p:
        if p.name in ('blockquote', 'q'):
            return True
        if p.name == 'div' and _has_quote_class(p):
            return True
        p = p.parent
    return False


def _find_quote_nodes(soup) -> list:
    nodes = list(soup.find_all(['blockquote', 'q']))
    for div in soup.find_all('div'):
        if _has_quote_class(div):
            nodes.append(div)
    return nodes


def _strip_nested_quote_nodes(nodes) -> None:
    for node in nodes:
        if _is_nested_in_quote(node):
            node.decompose()


def _quote_text_to_bbcode(text: str) -> str:
    m = _RE_QUOTE_QUOTING.match(text)
    if m:
        author = m.group(1).strip().strip('"“')
        content = m.group(2).strip()
        return f"\n[quote={author}]{content}[/quote]\n"
    m = _RE_QUOTE_SHORT.match(text)
    if m:
        author = m.group(1).strip()
        content = m.group(2).strip()
        return f"\n[quote={author}]{content}[/quote]\n"
    return f"\n[quote=Alguém]{text}[/quote]\n"


def _replace_quote_nodes_with_bbcode(nodes) -> None:
    for node in nodes:
        if not node.parent:
            continue
        for br in node.find_all("br"):
            br.replace_with("\n")
        node_text = node.get_text(separator="\n").strip()
        node.replace_with(_quote_text_to_bbcode(node_text))


def _soup_to_text(soup) -> str:
    for img in soup.find_all('img'):
        img.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for p in soup.find_all(['p', 'div', 'li']):
        p.append("\n")
    text = soup.get_text()
    lines = [line.strip(' \t\r') for line in text.split('\n')]
    text = "\n".join(lines)
    text = _RE_MULTI_BLANK.sub('\n\n', text)
    return text.replace("[img]", "").replace("[/img]", "").strip()


def _collapse_nested_bbcode_quotes(text: str) -> str:
    if '[quote=' not in text.lower():
        return text
    result = []
    depth = 0
    for token in _RE_QUOTE_TOKEN.split(text):
        t_lower = token.lower()
        if t_lower.startswith('[quote='):
            depth += 1
            if depth == 1:
                result.append(token)
        elif t_lower == '[/quote]':
            if depth > 0:
                if depth == 1:
                    result.append(token)
                depth -= 1
        elif depth <= 1:
            result.append(token)
    return "".join(result).strip()


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, HTML_PARSER)
    quote_nodes = _find_quote_nodes(soup)
    _strip_nested_quote_nodes(quote_nodes)
    _replace_quote_nodes_with_bbcode(quote_nodes)
    text = _soup_to_text(soup)
    return _collapse_nested_bbcode_quotes(text)


def extract_reply_content(text: str) -> str:
    text = text.replace("[*/quote]", "").replace("[* /quote]", "")

    m = _RE_REPLY_BBCODE.search(text)
    if m: return (m.group(2) or "").strip()

    m = _RE_REPLY_BB_QUOTE.search(text)
    if m: return (m.group(2) or "").strip()

    m = _RE_REPLY_QUOTING.match(text)
    if m:
        rest = m.group(1).strip()
        if '\n\n' in rest:
            parts = _RE_BLANKLINE_SPLIT.split(rest, maxsplit=1)
            return parts[1].strip()
        return ""

    m = _RE_REPLY_OLD.match(text)
    if m: return m.group(1).strip()

    return text


@dataclass(frozen=True)
class BridgeConfig:
    base_url: str
    ws_host: str
    chatroom_id: int
    tg_chat_id: int
    tg_topic_id: Optional[int]
    user_id: int
    imgbb_key: Optional[str]
    aliases: tuple
    csrf_token: str
    cookie: str

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"Variáveis obrigatórias ausentes no .env: {', '.join(missing)}")

        my_username = os.getenv("MY_USERNAME", "")
        aliases_set = set()
        if my_username:
            aliases_set.add(my_username.lower().lstrip("@"))
        for a in os.getenv("MY_ALIASES", "").split(","):
            clean_a = a.strip().lower().lstrip("@")
            if clean_a:
                aliases_set.add(clean_a)
        aliases = tuple(sorted(aliases_set, key=len, reverse=True))

        topic = os.getenv("TELEGRAM_TOPIC_ID")

        return cls(
            base_url=os.getenv("BASE_URL"),
            ws_host=_compose_ws_host(os.getenv("WS_HOST"), os.getenv("WS_PORT", "8443")),
            chatroom_id=int(os.getenv("CHATROOM_ID", 1)),
            tg_chat_id=int(os.getenv("TELEGRAM_CHAT_ID")),
            tg_topic_id=int(topic) if topic else None,
            user_id=int(os.getenv("USER_ID")),
            imgbb_key=os.getenv("IMGBB_API_KEY"),
            aliases=aliases,
            csrf_token=os.getenv("CSRF_TOKEN"),
            cookie=os.getenv("COOKIE"),
        )


class ChatBridge:
    def __init__(self, cfg: BridgeConfig):
        self.cfg = cfg
        self.base_url = cfg.base_url
        self.ws_host = cfg.ws_host
        self.chatroom_id = cfg.chatroom_id
        self.tg_chat_id = cfg.tg_chat_id
        self.tg_topic_id = cfg.tg_topic_id
        self.user_id = cfg.user_id
        self.imgbb_key = cfg.imgbb_key
        self.aliases = cfg.aliases

        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": cfg.csrf_token,
            "Cookie": cfg.cookie,
            "User-Agent": settings.user_agent,
        }

        self.client = httpx.AsyncClient(
            base_url=cfg.base_url, headers=self.headers,
            timeout=settings.http_timeout, follow_redirects=True,
        )
        self.upload_client = httpx.AsyncClient(timeout=settings.upload_timeout)

        self.last_seen_id = 0
        self.cache_limit = settings.msg_map_limit
        self.msg_map: "OrderedDict[int, Dict[str, Any]]" = OrderedDict()
        self.media_buffer: Dict[str, Dict] = {}

        self.ws_channel = f"presence-chatroom.{cfg.chatroom_id}"
        self.msg_queue: asyncio.Queue = asyncio.Queue()
        self.queued_ids: "OrderedDict[int, None]" = OrderedDict()
        self.queued_limit = settings.queued_dedup_limit
        self.ws_connected = asyncio.Event()

    @classmethod
    def from_env(cls) -> "ChatBridge":
        return cls(BridgeConfig.from_env())

    async def __aenter__(self) -> "ChatBridge":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self):
        await self.client.aclose()
        await self.upload_client.aclose()

    def _extract_all_image_urls(self, raw_html: str) -> List[str]:
        if not raw_html: return []
        soup = BeautifulSoup(raw_html, HTML_PARSER)
        urls = []
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                if not src.startswith("http"):
                    if src.startswith("/"): src = src[1:]
                    base = self.base_url if self.base_url.endswith("/") else self.base_url + "/"
                    src = base + src
                urls.append(src)
        return urls

    async def download_image(self, url: str) -> Optional[bytes]:
        client = self.upload_client if url.startswith("http") else self.client
        try:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.warning(f"download_image {url}: HTTP {response.status_code}")
                    return None
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                return bytes(chunks)
        except Exception as e:
            _log_http_failure(f"download_image {url}", e)
            return None

    async def upload_to_imgbb(self, image_data) -> str:
        if not self.imgbb_key:
            logger.error("IMGBB_API_KEY não configurada!")
            return ""
        try:
            payload = {"key": self.imgbb_key}
            if hasattr(image_data, 'read'):
                files = {"image": image_data}
            else:
                files = {"image": ("telegram_upload.jpg", bytes(image_data))}
            resp = await self.upload_client.post("https://api.imgbb.com/1/upload", data=payload, files=files)
            if resp.status_code == 200:
                return resp.json()['data']['url']
            logger.warning(f"upload_to_imgbb: HTTP {resp.status_code}")
            return ""
        except Exception as e:
            _log_http_failure("upload_to_imgbb", e)
            return ""

    async def process_media_group_delayed(self, gid: str, bot):
        await asyncio.sleep(settings.album_wait_seconds)
        if gid not in self.media_buffer: return

        data = self.media_buffer.pop(gid)
        photos = data['photos']
        text = data['text']
        reply_id = data['reply_to']
        status_msg = data['status_msg']

        async def _upload_one(photo_obj):
            try:
                file_obj = await bot.get_file(photo_obj.file_id)
                file_bytes = await file_obj.download_as_bytearray()
                return await self.upload_to_imgbb(file_bytes)
            except Exception as e:
                logger.warning(f"upload álbum item {photo_obj.file_id}: {e}")
                return ""

        results = await asyncio.gather(*[_upload_one(p) for p in photos])
        uploaded_urls = [u for u in results if u]

        bbcode_block = " ".join([f"[img]{u}[/img]" for u in uploaded_urls])
        final_text = f"{text}\n{bbcode_block}".strip()

        if not final_text:
            if status_msg:
                try: await status_msg.edit_text("❌ Falha no upload do álbum.")
                except: pass
            return

        payload = final_text
        if reply_id and reply_id in self.msg_map:
            payload = build_bbcode_payload(self.msg_map[reply_id], final_text)

        if await self.send_message(payload):
            if status_msg:
                try: await status_msg.edit_text("✅")
                except: pass
                await asyncio.sleep(2)
                try: await status_msg.delete()
                except: pass
        else:
            if status_msg:
                try: await status_msg.edit_text("❌ Erro envio site.")
                except: pass

    def _cache_message(self, tg_msg_id: int, site_msg_data: dict):
        user = site_msg_data.get("user") or {}
        handle = user.get("username") or user.get("name") or f"user{user.get('id')}"
        clean_text = clean_html(site_msg_data.get("message") or "")

        self.msg_map[tg_msg_id] = {
            "site_id": int(site_msg_data.get("id", 0)),
            "handle": str(handle).strip(),
            "text": extract_reply_content(clean_text),
        }
        while len(self.msg_map) > self.cache_limit:
            self.msg_map.popitem(last=False)

    async def fetch_messages(self) -> list:
        try:
            resp = await self.client.get(f"/api/chat/messages/{self.chatroom_id}")
            resp.raise_for_status()
            return resp.json().get("data", []) or []
        except Exception as e:
            _log_http_failure("fetch_messages", e)
            return []

    async def send_message(self, text: str) -> bool:
        if not text or not text.strip(): return False
        payload = {
            "user_id": self.user_id,
            "chatroom_id": self.chatroom_id,
            "message": text,
            "save": True,
            "targeted": 0,
            "receiver_id": None,
            "bot_id": None,
        }
        try:
            resp = await self.client.post("/api/chat/messages", json=payload)
            resp.raise_for_status()
            return True
        except Exception as e:
            _log_http_failure("send_message", e)
            return False

    async def delete_message(self, site_msg_id: int) -> bool:
        try:
            resp = await self.client.post(f"/api/chat/message/{site_msg_id}/delete")
            resp.raise_for_status()
            return True
        except Exception as e:
            _log_http_failure(f"delete_message {site_msg_id}", e)
            return False

    async def auth_ws_channel(self, socket_id: str) -> dict:
        try:
            resp = await self.client.post(
                "/broadcasting/auth",
                data={"socket_id": socket_id, "channel_name": self.ws_channel},
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": self.base_url + "/",
                    "Origin": self.base_url,
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            _log_http_failure("auth_ws_channel", e)
            raise

    async def probe_session(self) -> int:
        try:
            resp = await self.client.get(f"/api/chat/messages/{self.chatroom_id}")
            return resp.status_code
        except Exception as e:
            _log_http_failure("probe_session", e)
            return -1

    def find_tg_msg_id(self, site_id: int) -> Optional[int]:
        for tg_id, entry in self.msg_map.items():
            if entry.get("site_id") == site_id:
                return tg_id
        return None

    def enqueue_message(self, m: dict) -> bool:
        try:
            sid = int(m.get("id", 0))
        except (TypeError, ValueError):
            return False
        if sid <= 0 or sid in self.queued_ids:
            return False
        self.queued_ids[sid] = None
        while len(self.queued_ids) > self.queued_limit:
            self.queued_ids.popitem(last=False)
        if sid > self.last_seen_id:
            self.last_seen_id = sid
        self.msg_queue.put_nowait(m)
        return True
