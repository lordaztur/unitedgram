import asyncio
import html
import io
import logging
import re
import time
import uuid
from urllib.parse import unquote

import discord
import socketio
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    LinkPreviewOptions,
)
from telegram.error import BadRequest, NetworkError, RetryAfter
from telegram.ext import Application

from bridge import clean_html
from config import settings
from formatting import format_discord_body, format_discord_message, format_telegram_message

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

_NET_RETRY_BACKOFFS = (3, 7, 15)


def _extract_payload(args):
    for a in args:
        if isinstance(a, dict) and "message" in a: return a
        if isinstance(a, list) and a and isinstance(a[0], dict): return a[0]
    return None


# Pega .gif tanto no path quanto em URL embedada em query (ex.: wsrv.nl/?url=...giphy.gif).
# A âncora à direita evita falso-positivo em ".gifts/", ".gifford" etc.
_RE_GIF_IN_URL = re.compile(r'\.gif(?:[?&#/=]|$)', re.IGNORECASE)


def _is_gif(item) -> bool:
    if isinstance(item, (bytes, bytearray)):
        return bytes(item[:4]) == b"GIF8"
    if isinstance(item, str):
        return bool(_RE_GIF_IN_URL.search(unquote(item)))
    return False


async def _send_to_telegram(app: Application, bridge, images, text_out, reply_markup, avatar_url=None):
    if not app:
        return None
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
        if _is_gif(images[0]):
            return await app.bot.send_animation(
                chat_id=bridge.tg_chat_id,
                message_thread_id=bridge.tg_topic_id,
                animation=images[0],
                caption=text_out[:1024],
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return await app.bot.send_photo(
            chat_id=bridge.tg_chat_id,
            message_thread_id=bridge.tg_topic_id,
            photo=images[0],
            caption=text_out[:1024],
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    preview = (
        LinkPreviewOptions(url=avatar_url, prefer_small_media=True)
        if avatar_url else NO_PREVIEW
    )
    return await app.bot.send_message(
        chat_id=bridge.tg_chat_id,
        message_thread_id=bridge.tg_topic_id,
        text=text_out,
        parse_mode="HTML",
        link_preview_options=preview,
        reply_markup=reply_markup,
    )


async def _send_fallback_text(app: Application, bridge, raw_html: str):
    if not app:
        return
    return await app.bot.send_message(
        chat_id=bridge.tg_chat_id,
        message_thread_id=bridge.tg_topic_id,
        text=f"💬 {html.escape(clean_html(raw_html))}",
        parse_mode="HTML",
        link_preview_options=NO_PREVIEW,
    )


async def deliver_message(bridge, app: Application, discord_bot, m: dict):
    site_id = int(m.get("id", 0))
    raw_html = m.get('message') or ""
    img_urls = bridge._extract_all_image_urls(raw_html)

    text_tg = format_telegram_message(bridge, m) if settings.enable_telegram else ""
    text_ds = format_discord_message(bridge, m) if settings.enable_discord else ""

    user_data = m.get("user") or {}
    m_username = user_data.get("username") or user_data.get("name") or ""
    is_me = m_username.lower().lstrip("@") in bridge.aliases

    reply_markup = None
    if is_me and settings.show_delete_button:
        keyboard = [[InlineKeyboardButton("🗑️ Deletar", callback_data=f"del_{site_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

    images: list = []
    if img_urls:
        async def _resolve(url: str):
            if bridge.is_internal_image(url):
                data = await bridge.download_image(url)
                if data is not None:
                    return data
                logger.warning(f"deliver_message {site_id}: download interno falhou; tentando URL direta {url}")
            return url
        images = list(await asyncio.gather(*[_resolve(u) for u in img_urls]))

    avatar_url = None if images else await bridge.get_avatar_url(user_data)

    sent_msg_tg = None
    transient_failure = False

    # Entrega Telegram
    if settings.enable_telegram and app and text_tg:
        for attempt in range(len(_NET_RETRY_BACKOFFS) + 1):
            try:
                sent_msg_tg = await _send_to_telegram(app, bridge, images, text_tg, reply_markup, avatar_url)
                break
            except RetryAfter as e:
                transient_failure = True
                logger.info(f"deliver_message {site_id} (TG): RetryAfter {e.retry_after}s (tentativa {attempt + 1})")
                await asyncio.sleep(int(e.retry_after) + 2)
            except BadRequest as e:
                transient_failure = False
                logger.warning(f"deliver_message {site_id} (TG): BadRequest, fallback texto: {e}")
                try:
                    sent_msg_tg = await _send_fallback_text(app, bridge, raw_html)
                except Exception as inner:
                    logger.error(f"deliver_message {site_id} (TG): fallback falhou: {inner}")
                break
            except NetworkError as e:
                transient_failure = True
                if attempt >= len(_NET_RETRY_BACKOFFS):
                    logger.error(f"deliver_message {site_id} (TG): erro de rede após {attempt + 1} tentativas: {e}")
                    break
                wait = _NET_RETRY_BACKOFFS[attempt]
                logger.warning(f"deliver_message {site_id} (TG): erro de rede ({e}); retry em {wait}s (tentativa {attempt + 1})")
                await asyncio.sleep(wait)
            except Exception as e:
                transient_failure = False
                logger.error(f"Erro enviando msg {site_id} p/ Telegram: {e}")
                break

    # Entrega Discord
    sent_msg_ds_id = None
    if settings.enable_discord and discord_bot and text_ds:
        try:
            channel = discord_bot.get_channel(discord_bot.channel_id)
            if channel:
                avatar_bytes, ext = await bridge.get_discord_avatar(user_data)
                if avatar_bytes:
                    file = discord.File(io.BytesIO(avatar_bytes), filename=f"avatar.{ext}")

                    # Estilo solicitado pelo usuário
                    # Usamos apenas o texto da mensagem na descrição, já que o nome está no autor
                    clean_text = clean_html(m.get("message") or "")
                    description = format_discord_body(bridge, clean_text)

                    # Extração da cor do usuário (do grupo ou status)
                    user_color = 0x5865F2  # Azul padrão
                    if m.get("type") == "notification":
                        user_color = 0xFE0203
                    else:
                        group_data = user_data.get("group") or {}
                        hex_color = group_data.get("color") or (user_data.get("chat_status") or {}).get("color")
                        if hex_color and hex_color.startswith("#"):
                            try:
                                user_color = int(hex_color.lstrip("#"), 16)
                            except ValueError:
                                pass

                    embed = discord.Embed(description=description if description else "(Mensagem vazia)", color=user_color)

                    # Footer com a data da mensagem (apenas o horário)
                    msg_date = m.get("created_at") or m.get("date") or time.strftime("%H:%M:%S")
                    if "T" in msg_date:
                        # Extrai HH:MM:SS de 2026-05-15T17:12:36-03:00
                        msg_date = msg_date.split("T")[1].split("-")[0].split("+")[0]
                    embed.set_footer(text=msg_date)

                    # Autor com o nome do usuário e o ícone (avatar)
                    embed.set_author(name=m_username if m_username else "Sistema", icon_url=f"attachment://avatar.{ext}")

                    msg_ds = await channel.send(file=file, embed=embed)
                    if is_me and settings.show_delete_button:
                        try:
                            await msg_ds.add_reaction("🗑️")
                        except:
                            pass
                else:
                    msg_ds = await channel.send(text_ds)
                    if is_me and settings.show_delete_button:
                        try:
                            await msg_ds.add_reaction("🗑️")
                        except:
                            pass
                sent_msg_ds_id = msg_ds.id
        except Exception as e:
            logger.error(f"Erro enviando msg {site_id} p/ Discord: {e}")

    if sent_msg_tg:
        bridge._cache_message(sent_msg_tg.message_id, m)
    if sent_msg_ds_id:
        bridge._cache_message(sent_msg_ds_id, m)

    if not sent_msg_tg and not sent_msg_ds_id and transient_failure:
        # Libera o ID do dedup pra um reconcile via HTTP poder recuperar a msg.
        bridge.queued_ids.pop(site_id, None)
        logger.error(f"deliver_message {site_id}: não entregue (erro transitório) — ID liberado p/ reconcile")
    else:
        logger.error(f"deliver_message {site_id}: não entregue (erro permanente) — descartada")


async def message_worker(bridge, app: Application, discord_bot=None):
    while True:
        m = await bridge.msg_queue.get()
        try:
            await deliver_message(bridge, app, discord_bot, m)
        except Exception as e:
            logger.error(f"Worker error: {e}")
        finally:
            bridge.msg_queue.task_done()


async def heartbeat(bridge):
    start = time.monotonic()
    while True:
        await asyncio.sleep(settings.heartbeat_interval)
        qsize = bridge.msg_queue.qsize() if bridge.msg_queue else 0
        uptime = int(time.monotonic() - start)
        logger.info(f"💓 uptime={uptime}s queue={qsize} ws={bridge.ws_connected.is_set()}")


async def cookie_health_probe(bridge, app: Application):
    alerted = False
    while True:
        await asyncio.sleep(settings.cookie_probe_interval)
        success = await bridge.update_session_data()
        if not success:
            if not alerted:
                logger.error("🚨 Sessão expirou ou falha ao atualizar cookies. Atualize cookies.txt e CSRF_TOKEN.")
                if not app:
                    alerted = True
                    continue
                try:
                    await app.bot.send_message(
                        chat_id=bridge.tg_chat_id,
                        message_thread_id=bridge.tg_topic_id,
                        text=(
                            f"🚨 <b>Sessão expirada ou Erro de Rede</b>\n"
                            f"Falha ao atualizar cookies em <code>{bridge.base_url}</code>.\n"
                            f"Atualize <code>cookies/cookies.txt</code> e reinicie."
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Não consegui enviar alerta no Telegram: {e}")
                alerted = True
        elif success and alerted:
            logger.info("✅ Sessão recuperada")
            alerted = False
        elif success:
            logger.info("✅ Cookies atualizados e salvos com sucesso")


async def initial_backfill(bridge):
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


async def reconcile_via_http(bridge):
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
    def __init__(self, bridge, app: Application):
        self.app = app
        self.bridge = bridge
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
                asyncio.create_task(reconcile_via_http(bridge))

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
                if app:
                    await app.bot.delete_message(chat_id=bridge.tg_chat_id, message_id=tg_msg_id)
                    logger.info(f"   → Telegram msg {tg_msg_id} deletada (mirror)")
                bridge.msg_map.pop(tg_msg_id, None)
            except Exception as e:
                logger.warning(f"   falha ao deletar Telegram msg {tg_msg_id}: {e}")

        @sio.on("presence:subscribed")
        async def on_presence_subscribed(*args):
            bridge.ws_connected.set()
            members = next((a for a in args if isinstance(a, list)), [])
            bridge.seed_online(members)
            logger.info(f"✅ Presence subscribed: {len(bridge.online)} online")

        @sio.on("presence:joining")
        async def on_presence_joining(*args):
            payload = next((a for a in args if isinstance(a, dict)), None)
            if not payload:
                return
            try:
                uid = int(payload.get("user_id"))
            except (TypeError, ValueError):
                return
            info = payload.get("user_info") or {}
            uname = info.get("username") or info.get("name")
            if uid and uname:
                bridge.mark_online(uid, str(uname))

        @sio.on("presence:leaving")
        async def on_presence_leaving(*args):
            payload = next((a for a in args if isinstance(a, dict)), None)
            if not payload:
                return
            try:
                uid = int(payload.get("user_id"))
            except (TypeError, ValueError):
                return
            if uid:
                bridge.mark_offline(uid)

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
            headers={"Cookie": self.bridge.get_cookie_string(), "Origin": self.bridge.base_url},
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


async def _safety_reconciler(bridge):
    while True:
        await asyncio.sleep(settings.safety_reconcile_interval)
        if not bridge.ws_connected.is_set():
            await reconcile_via_http(bridge)


async def run_websocket(bridge, app: Application):
    safety_task = asyncio.create_task(_safety_reconciler(bridge))
    backoff = settings.ws_backoff_initial
    try:
        while True:
            session = WsSession(bridge, app)
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
