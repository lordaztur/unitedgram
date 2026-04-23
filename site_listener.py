import asyncio
import html
import logging
import time
import uuid

import socketio
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    LinkPreviewOptions,
)
from telegram.error import BadRequest, RetryAfter
from telegram.ext import Application

from bridge import clean_html
from config import settings
from formatting import format_telegram_message

logger = logging.getLogger(__name__)

__all__ = [
    "deliver_message",
    "message_worker",
    "heartbeat",
    "cookie_health_probe",
    "initial_backfill",
    "reconcile_via_http",
    "run_websocket",
    "WsSession",
]

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _extract_payload(args):
    for a in args:
        if isinstance(a, dict) and "message" in a: return a
        if isinstance(a, list) and a and isinstance(a[0], dict): return a[0]
    return None


async def _send_to_telegram(app: Application, bridge, images, text_out, reply_markup):
    if len(images) > 1:
        media_group = [
            InputMediaPhoto(img, caption=text_out[:1024] if i == 0 else "", parse_mode="HTML")
            for i, img in enumerate(images)
        ]
        msgs = await app.bot.send_media_group(
            chat_id=bridge.tg_chat_id,
            message_thread_id=bridge.tg_topic_id,
            media=media_group,
        )
        return msgs[0]
    if len(images) == 1:
        return await app.bot.send_photo(
            chat_id=bridge.tg_chat_id,
            message_thread_id=bridge.tg_topic_id,
            photo=images[0],
            caption=text_out[:1024],
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    return await app.bot.send_message(
        chat_id=bridge.tg_chat_id,
        message_thread_id=bridge.tg_topic_id,
        text=text_out,
        parse_mode="HTML",
        link_preview_options=NO_PREVIEW,
        reply_markup=reply_markup,
    )


async def _send_fallback_text(app: Application, bridge, raw_html: str):
    return await app.bot.send_message(
        chat_id=bridge.tg_chat_id,
        message_thread_id=bridge.tg_topic_id,
        text=f"💬 {html.escape(clean_html(raw_html))}",
        parse_mode="HTML",
        link_preview_options=NO_PREVIEW,
    )


async def deliver_message(app: Application, m: dict):
    bridge = app.bot_data['bridge']
    site_id = int(m.get("id", 0))
    raw_html = m.get('message') or ""
    img_urls = bridge._extract_all_image_urls(raw_html)
    text_out = format_telegram_message(bridge, m)

    user_data = m.get("user") or {}
    m_username = user_data.get("username") or user_data.get("name") or ""
    is_me = m_username.lower().lstrip("@") in bridge.aliases

    reply_markup = None
    if is_me and settings.show_delete_button:
        keyboard = [[InlineKeyboardButton("🗑️ Deletar", callback_data=f"del_{site_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

    images: list[bytes] = []
    if img_urls:
        downloads = await asyncio.gather(*[bridge.download_image(u) for u in img_urls])
        images = [b for b in downloads if b]

    sent_msg = None
    for attempt in range(3):
        try:
            sent_msg = await _send_to_telegram(app, bridge, images, text_out, reply_markup)
            break
        except RetryAfter as e:
            logger.info(f"deliver_message {site_id}: RetryAfter {e.retry_after}s (tentativa {attempt+1})")
            await asyncio.sleep(int(e.retry_after) + 2)
            continue
        except BadRequest as e:
            logger.warning(f"deliver_message {site_id}: BadRequest, fallback texto: {e}")
            try:
                sent_msg = await _send_fallback_text(app, bridge, raw_html)
            except Exception as inner:
                logger.error(f"deliver_message {site_id}: fallback falhou: {inner}")
            break
        except Exception as e:
            logger.error(f"Erro enviando msg {site_id} p/ Telegram: {e}")
            break

    if sent_msg:
        bridge._cache_message(sent_msg.message_id, m)


async def message_worker(app: Application):
    bridge = app.bot_data['bridge']
    while True:
        m = await bridge.msg_queue.get()
        try:
            await deliver_message(app, m)
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            bridge.msg_queue.task_done()


async def heartbeat(app: Application):
    bridge = app.bot_data['bridge']
    start = time.monotonic()
    while True:
        await asyncio.sleep(settings.heartbeat_interval)
        qsize = bridge.msg_queue.qsize() if bridge.msg_queue else 0
        uptime = int(time.monotonic() - start)
        logger.info(f"💓 uptime={uptime}s queue={qsize} ws={bridge.ws_connected.is_set()}")


async def cookie_health_probe(app: Application):
    bridge = app.bot_data['bridge']
    alerted = False
    while True:
        await asyncio.sleep(settings.cookie_probe_interval)
        status = await bridge.probe_session()
        if status in (401, 403, 419):
            if not alerted:
                logger.error(f"🚨 Sessão expirou (HTTP {status}). Atualize COOKIE/CSRF_TOKEN no .env.")
                try:
                    await app.bot.send_message(
                        chat_id=bridge.tg_chat_id,
                        message_thread_id=bridge.tg_topic_id,
                        text=(
                            f"🚨 <b>Sessão expirada</b>\n"
                            f"HTTP {status} em <code>{bridge.base_url}</code>.\n"
                            f"Atualize <code>COOKIE</code> e <code>CSRF_TOKEN</code> no <code>.env</code> e reinicie."
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Não consegui enviar alerta no Telegram: {e}")
                alerted = True
        elif status == 200 and alerted:
            logger.info("✅ Sessão recuperada")
            alerted = False


async def initial_backfill(app: Application):
    bridge = app.bot_data['bridge']
    try:
        initial = await bridge.fetch_messages()
        if not initial:
            return
        initial.sort(key=lambda x: int(x.get("id", 0)))
        n = settings.backfill_count
        keep = initial[-n:] if n > 0 else []
        old = initial[:-n] if n > 0 else initial
        for m in old:
            try:
                sid = int(m.get("id", 0))
            except (TypeError, ValueError):
                continue
            if sid <= 0: continue
            bridge.queued_ids[sid] = None
        if keep:
            bridge.last_seen_id = int(keep[0]['id']) - 1
        elif initial:
            bridge.last_seen_id = int(initial[-1]['id'])
        logger.info(f"📥 Backfill: entregando últimas {len(keep)} msg(s), ignorando {len(old)} mais antiga(s)")
    except Exception as e:
        logger.error(f"Erro no backfill inicial: {e}")


async def reconcile_via_http(app: Application):
    bridge = app.bot_data['bridge']
    try:
        msgs = await bridge.fetch_messages()
        msgs.sort(key=lambda x: int(x.get("id", 0)))
        new = 0
        for m in msgs:
            if bridge.enqueue_message(m): new += 1
        if new:
            logger.info(f"🔄 Reconciliação via HTTP: {new} msg(s) recuperadas")
    except Exception as e:
        logger.error(f"Erro na reconciliação: {e}")


class WsSession:
    def __init__(self, app: Application):
        self.app = app
        self.bridge = app.bot_data['bridge']
        self.sio = socketio.AsyncClient(reconnection=False, logger=False, engineio_logger=False)
        self._register_handlers()

    def _register_handlers(self):
        sio = self.sio
        bridge = self.bridge
        app = self.app

        @sio.on("connect")
        async def on_connect():
            logger.info(f"🔌 WS conectado (sid={sio.sid})")
            if await self._subscribe():
                asyncio.create_task(reconcile_via_http(app))

        @sio.on("disconnect")
        async def on_disconnect():
            bridge.ws_connected.clear()
            logger.warning("🔌 WS desconectado")

        @sio.on("connect_error")
        async def on_connect_error(data=None):
            logger.error(f"❌ Erro de conexão WS: {data}")

        @sio.on("new.message")
        async def on_new_message(*args):
            payload = _extract_payload(args)
            if not payload: return
            m = payload.get("message") or payload
            if bridge.enqueue_message(m):
                logger.info(f"💬 Nova msg via WS id={m.get('id')}")

        @sio.on("delete.message")
        async def on_delete_message(*args):
            payload = _extract_payload(args)
            if not payload: return
            msg = payload.get("message") or {}
            site_id = msg.get("id")
            logger.info(f"🗑️  delete.message do site id={site_id}")
            if not settings.mirror_deletions:
                return
            try:
                site_id_int = int(site_id)
            except (TypeError, ValueError):
                return
            tg_msg_id = bridge.find_tg_msg_id(site_id_int)
            if not tg_msg_id:
                logger.debug(f"   msg site id={site_id_int} fora do cache; nada a deletar")
                return
            try:
                await app.bot.delete_message(chat_id=bridge.tg_chat_id, message_id=tg_msg_id)
                bridge.msg_map.pop(tg_msg_id, None)
                logger.info(f"   → Telegram msg {tg_msg_id} deletada (mirror)")
            except Exception as e:
                logger.warning(f"   falha ao deletar Telegram msg {tg_msg_id}: {e}")

        @sio.on("presence:subscribed")
        async def on_presence_subscribed(*args):
            bridge.ws_connected.set()
            logger.info(f"✅ Presence subscribed: {str(args)[:120]}")

        @sio.on("subscription_error")
        async def on_sub_error(*args):
            logger.warning(f"⚠️  subscription_error: {args}. Forçando reconexão...")
            asyncio.create_task(sio.disconnect())

    async def _subscribe(self) -> bool:
        try:
            auth = await self.bridge.auth_ws_channel(self.sio.sid)
        except Exception as e:
            logger.error(f"❌ Falha no /broadcasting/auth: {e}")
            return False
        cd = auth.get("channel_data")
        if isinstance(cd, dict) and "user_id" in cd:
            cd = dict(cd)
            cd["user_id"] = f"bot-{uuid.uuid4().hex[:12]}"
        payload = {
            "channel": self.bridge.ws_channel,
            "auth": auth.get("auth"),
            "channel_data": cd,
        }
        await self.sio.emit("subscribe", payload)
        logger.info(f"📡 Subscribe enviado para {self.bridge.ws_channel}")
        return True

    async def run(self):
        await self.sio.connect(
            self.bridge.ws_host,
            transports=["websocket"],
            headers={"Cookie": self.bridge.headers["Cookie"], "Origin": self.bridge.base_url},
            socketio_path=settings.ws_path,
        )
        await self.sio.wait()

    async def close(self):
        if not self.sio.connected:
            return
        try:
            await self.sio.emit("unsubscribe", {"channel": self.bridge.ws_channel})
            await asyncio.sleep(0.5)
        except Exception:
            pass
        try:
            await self.sio.disconnect()
        except Exception:
            pass


async def _safety_reconciler(app: Application):
    bridge = app.bot_data['bridge']
    while True:
        await asyncio.sleep(settings.safety_reconcile_interval)
        if not bridge.ws_connected.is_set():
            await reconcile_via_http(app)


async def run_websocket(app: Application):
    safety_task = asyncio.create_task(_safety_reconciler(app))
    backoff = settings.ws_backoff_initial
    try:
        while True:
            session = WsSession(app)
            try:
                await session.run()
                backoff = settings.ws_backoff_initial
            except asyncio.CancelledError:
                await session.close()
                raise
            except Exception as e:
                logger.error(f"Loop WS: {e}")
            finally:
                await session.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, settings.ws_backoff_max)
    finally:
        safety_task.cancel()
