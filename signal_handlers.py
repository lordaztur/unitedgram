import asyncio
import base64
import contextlib
import json
import logging
import os
import time
from collections import OrderedDict
from urllib.parse import urlparse

import httpx
import websockets

from bridge import ChatBridge, clean_html
from formatting import build_bbcode_payload, format_signal_message

logger = logging.getLogger(__name__)

__all__ = ["SignalBot"]

_RECONNECT_BACKOFFS = (3, 5, 10, 20, 30, 60)
_SELF_SENT_TTL_SECONDS = 120
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


class SignalBot:
    def __init__(self, bridge: ChatBridge):
        self.bridge = bridge
        self.api_url = os.getenv("SIGNAL_API_URL", "http://localhost:8080").rstrip("/")
        self.phone = os.getenv("SIGNAL_PHONE", "")
        self.recipient = os.getenv("SIGNAL_RECIPIENT", "")
        self.client = httpx.AsyncClient(base_url=self.api_url, timeout=30.0)
        self._self_sent_timestamps: "OrderedDict[int, float]" = OrderedDict()
        self._stop = asyncio.Event()
        self._ws_url = self._build_ws_url()

    def _build_ws_url(self) -> str:
        parsed = urlparse(self.api_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return f"{scheme}://{parsed.netloc}/v1/receive/{self.phone}"

    async def start(self):
        if not self.phone or not self.recipient:
            logger.warning("SIGNAL_PHONE ou SIGNAL_RECIPIENT não configurado, pulando Signal.")
            return
        logger.info(f"🔌 Signal conectando em {self.api_url} como {self.phone}")
        backoff_idx = 0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._ws_url, ping_interval=30) as ws:
                    logger.info(f"✅ Signal WS conectado (recipient={self.recipient})")
                    backoff_idx = 0
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        await self._handle_envelope(raw)
            except asyncio.CancelledError:
                break
            except Exception as e:
                wait = _RECONNECT_BACKOFFS[min(backoff_idx, len(_RECONNECT_BACKOFFS) - 1)]
                logger.warning(f"Signal WS caiu ({type(e).__name__}: {e}); retry em {wait}s")
                backoff_idx += 1
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=wait)

    async def close(self):
        self._stop.set()
        await self.client.aclose()

    def _remember_self_sent(self, timestamp: int) -> None:
        now = time.time()
        self._self_sent_timestamps[timestamp] = now
        cutoff = now - _SELF_SENT_TTL_SECONDS
        while self._self_sent_timestamps:
            oldest_ts, oldest_t = next(iter(self._self_sent_timestamps.items()))
            if oldest_t >= cutoff:
                break
            self._self_sent_timestamps.popitem(last=False)

    def _is_self_echo(self, timestamp: int) -> bool:
        return timestamp in self._self_sent_timestamps

    async def _handle_envelope(self, raw):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug(f"Signal: payload não-JSON ignorado")
            return
        env = data.get("envelope", {})
        ts = int(env.get("timestamp") or 0)
        if not ts:
            return
        if self._is_self_echo(ts):
            return

        sync = (env.get("syncMessage") or {}).get("sentMessage") or {}
        data_msg = env.get("dataMessage") or {}

        if sync and self._destination_matches(sync):
            await self._process_incoming(sync, env, source_self=True)
        elif data_msg and self._destination_matches(data_msg):
            await self._process_incoming(data_msg, env, source_self=False)

    def _destination_matches(self, msg: dict) -> bool:
        group = (msg.get("groupInfo") or {}).get("groupId")
        if group:
            return self.recipient == group or self.recipient == f"group.{group}"
        dest = msg.get("destination")
        if dest:
            return self.recipient == dest
        return False

    async def _process_incoming(self, msg: dict, env: dict, source_self: bool):
        text = (msg.get("message") or "").strip()
        attachments = msg.get("attachments") or []

        if text.startswith("!"):
            await self._handle_command(text, env)
            return

        bbcode_img = ""
        for att in attachments:
            ctype = (att.get("contentType") or "").lower()
            if not ctype.startswith("image/"):
                continue
            att_id = att.get("id")
            if not att_id:
                continue
            img_bytes = await self._download_attachment(att_id)
            if not img_bytes:
                continue
            filename = att.get("filename") or f"signal_{att_id}.jpg"
            img_url = await self.bridge.upload_to_imgbb(img_bytes, ephemeral=True, filename=filename)
            if img_url:
                bbcode_img += f"[img]{img_url}[/img] "

        if not text and not bbcode_img:
            return

        final_text = f"{text}\n{bbcode_img}".strip()
        payload = final_text

        quote = msg.get("quote") or {}
        quoted_ts = quote.get("id") or quote.get("timestamp")
        if quoted_ts and quoted_ts in self.bridge.msg_map:
            payload = build_bbcode_payload(self.bridge.msg_map[quoted_ts], final_text)

        await self.bridge.send_message(payload)

    async def _download_attachment(self, att_id: str) -> bytes | None:
        try:
            resp = await self.client.get(f"/v1/attachments/{att_id}")
            if resp.status_code == 200:
                return resp.content
            logger.warning(f"Signal attachment {att_id}: HTTP {resp.status_code}")
        except Exception as e:
            logger.warning(f"Signal attachment {att_id}: {type(e).__name__}: {e}")
        return None

    async def _handle_command(self, text: str, env: dict):
        cmd = text.lower()
        if cmd == "!ping":
            await self.send_text("pong 🏓")
        elif cmd == "!online":
            if not self.bridge.online:
                await self.send_text("📭 Ninguém online no chat agora.")
                return
            names = sorted(self.bridge.online.values(), key=str.lower)
            body = "\n".join(f"• {n}" for n in names)
            await self.send_text(f"👥 {len(names)} online\n{body}")

    async def send_text(self, text: str, quote_timestamp: int | None = None, quote_author: str | None = None) -> int | None:
        if not text:
            return None
        payload = {"number": self.phone, "recipients": [self.recipient], "message": text}
        if quote_timestamp and quote_author:
            payload["quote_timestamp"] = quote_timestamp
            payload["quote_author"] = quote_author
        return await self._post_send(payload)

    async def send_image(self, image_bytes: bytes, caption: str = "", filename: str = "image.jpg") -> int | None:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "number": self.phone,
            "recipients": [self.recipient],
            "message": caption or "",
            "base64_attachments": [f"data:image/jpeg;base64,{b64};filename={filename}"],
        }
        return await self._post_send(payload)

    async def _post_send(self, payload: dict) -> int | None:
        try:
            resp = await self.client.post("/v2/send", json=payload, timeout=60.0)
            resp.raise_for_status()
            body = resp.json() if resp.content else {}
            ts = int(body.get("timestamp") or 0)
            if ts:
                self._remember_self_sent(ts)
            return ts or None
        except Exception as e:
            logger.error(f"Signal send falhou: {type(e).__name__}: {e}")
            return None

    async def send_site_message(self, bridge, msg_data: dict, images: list) -> int | None:
        text = format_signal_message(bridge, msg_data)
        if images and isinstance(images[0], (bytes, bytearray)):
            return await self.send_image(bytes(images[0]), caption=text)
        if images and isinstance(images[0], str):
            return await self.send_text(f"{text}\n{images[0]}")
        return await self.send_text(text)
