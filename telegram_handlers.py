import asyncio
import time

from telegram import Update
from telegram.ext import ContextTypes

from bridge import ChatBridge
from formatting import build_bbcode_payload

__all__ = ["check_chat", "ping", "status", "delete_callback", "forward_handler"]


def check_chat(update: Update, bridge: ChatBridge) -> bool:
    if not update.effective_chat or update.effective_chat.id != bridge.tg_chat_id: return False
    if bridge.tg_topic_id and getattr(update.effective_message, "message_thread_id", None) != bridge.tg_topic_id: return False
    return True


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_chat(update, context.bot_data['bridge']): await update.message.reply_text("pong 🏓")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bridge: ChatBridge = context.bot_data['bridge']
    if not check_chat(update, bridge):
        return
    start = context.bot_data.get('start_time', time.monotonic())
    uptime = int(time.monotonic() - start)
    qsize = bridge.msg_queue.qsize()
    ws = "✅ conectado" if bridge.ws_connected.is_set() else "❌ desconectado"
    text = (
        "📊 <b>Status</b>\n"
        f"uptime: <code>{uptime}s</code>\n"
        f"ws: {ws}\n"
        f"queue: <code>{qsize}</code>\n"
        f"last_seen_id: <code>{bridge.last_seen_id}</code>\n"
        f"msg_map: <code>{len(bridge.msg_map)}</code>\n"
        f"queued_ids: <code>{len(bridge.queued_ids)}</code>"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bridge = context.bot_data['bridge']
    try:
        data = query.data.split("_")
        if len(data) != 2 or data[0] != "del": return
        site_id = int(data[1])
        if await bridge.delete_message(site_id):
            await query.answer("🗑️ Mensagem apagada!")
            try: await query.message.delete()
            except Exception: await query.edit_message_text("🗑️ (Apagada)")
        else:
            await query.answer("❌ Erro ao apagar no site.", show_alert=True)
    except Exception: await query.answer("Erro interno.")


async def forward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bridge = context.bot_data['bridge']
    if not check_chat(update, bridge): return

    text = (update.message.text or update.message.caption or "").strip()
    reply = update.message.reply_to_message
    gid = update.message.media_group_id

    if gid:
        if gid not in bridge.media_buffer:
            status_msg = await update.message.reply_text("⏳ Processando álbum...")
            bridge.media_buffer[gid] = {
                'text': text,
                'photos': [],
                'reply_to': reply.message_id if reply else None,
                'status_msg': status_msg
            }
            asyncio.create_task(bridge.process_media_group_delayed(gid, context.bot))
        else:
            if not bridge.media_buffer[gid]['text'] and text: bridge.media_buffer[gid]['text'] = text
        if update.message.photo: bridge.media_buffer[gid]['photos'].append(update.message.photo[-1])
        return

    bbcode_img = ""
    if update.message.photo:
        try:
            photo = update.message.photo[-1]
            file_obj = await context.bot.get_file(photo.file_id)
            file_bytes = await file_obj.download_as_bytearray()
            img_url = await bridge.upload_to_imgbb(file_bytes)
            if img_url: bbcode_img = f"[img]{img_url}[/img]"
            else: await update.message.reply_text("❌ Falha no upload.")
        except Exception: pass

    if not text and not bbcode_img: return
    final_text = f"{text}\n{bbcode_img}".strip()

    if reply and reply.message_id in bridge.msg_map:
        payload = build_bbcode_payload(bridge.msg_map[reply.message_id], final_text)
    else: payload = final_text

    if await bridge.send_message(payload):
        confirm = await update.message.reply_text("✅")
        await asyncio.sleep(2)
        try: await update.message.delete(); await confirm.delete()
        except: pass
