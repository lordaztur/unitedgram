import contextlib
import logging
import os

import discord
from discord.ext import commands

from bridge import ChatBridge
from formatting import build_bbcode_payload
from site_listener import schedule_reaction_update
from stickers import process_discord_sticker, sticker_bbcode

logger = logging.getLogger(__name__)

__all__ = ["DiscordBot"]

class DiscordBot(commands.Bot):
    def __init__(self, bridge: ChatBridge):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.bridge = bridge
        self.channel_id = int(os.getenv("DISCORD_CHANNEL_ID", 0))

    async def on_ready(self):
        logger.info(f"🔌 Discord conectado como {self.user} (ID: {self.user.id})")

    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return

        if message.channel.id != self.channel_id:
            return

        if message.content.startswith("!"):
            await self.process_commands(message)
            return

        text = message.content.strip()
        bbcode_img = ""

        if message.attachments and not self.bridge.image_host_configured:
            logger.warning("Anexo detectado no Discord, mas a API key do host de imagens não está configurada.")

        if message.attachments:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
                    try:
                        img_bytes = await attachment.read()
                        img_url = await self.bridge.upload_image(img_bytes, ephemeral=True, filename=attachment.filename)
                        if img_url:
                            bbcode_img += f"[img]{img_url}[/img] "
                        else:
                            logger.warning(f"Falha ao subir anexo do Discord: {attachment.filename}")
                            with contextlib.suppress(BaseException):
                                await message.reply(f"❌ Falha no upload da imagem: {attachment.filename}")
                    except Exception as e:
                        logger.error(f"Erro ao processar anexo do Discord: {e}")
                        with contextlib.suppress(BaseException):
                            await message.reply(f"⚠️ Erro interno ao processar imagem: {attachment.filename}")

        if message.stickers:
            for sticker_item in message.stickers:
                try:
                    result = await process_discord_sticker(sticker_item, self.bridge.upload_client)
                    if not result:
                        continue
                    data, ext = result
                    img_url = await self.bridge.upload_image(data, ephemeral=True, filename=f"sticker.{ext}")
                    if img_url:
                        bbcode_img += f"{sticker_bbcode(img_url)} "
                except Exception as e:
                    logger.error(f"Erro ao processar sticker do Discord ({sticker_item.id}): {e}")

        if not text and not bbcode_img:
            return

        final_text = f"{text}\n{bbcode_img}".strip()

        payload = final_text
        if message.reference and message.reference.message_id:
            orig_msg_id = message.reference.message_id
            if orig_msg_id in self.bridge.msg_map:
                payload = build_bbcode_payload(self.bridge.msg_map[orig_msg_id], final_text)
            else:
                logger.info(f"on_message: reply para msg {orig_msg_id} sem quote (não está no msg_map; size={len(self.bridge.msg_map)})")

        if await self.bridge.send_message(payload):
            with contextlib.suppress(Exception):
                await message.delete()
        else:
            with contextlib.suppress(Exception):
                await message.add_reaction("👎")

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Evento raw (e não on_reaction_add) pra funcionar também em msgs fora do cache
        # do discord.py, ex.: enviadas antes de um restart.
        if payload.user_id == self.user.id or payload.channel_id != self.channel_id:
            return
        if payload.member and payload.member.bot:
            return
        emoji = payload.emoji
        if emoji.is_custom_emoji():
            return
        cached = self.bridge.msg_map.get(payload.message_id)
        if not cached:
            return
        channel = self.get_channel(self.channel_id)
        partial = channel.get_partial_message(payload.message_id) if channel else None

        if str(emoji) == "🗑️":
            if await self.bridge.delete_message(cached["site_id"]):
                if partial:
                    try:
                        await partial.delete()
                    except Exception as e:
                        logger.warning(f"Erro ao deletar msg no Discord: {e}")
            elif partial:
                with contextlib.suppress(Exception):
                    await partial.remove_reaction(emoji, discord.Object(payload.user_id))
            return

        # Reação feita no Discord vira reação no site; a nativa é removida e o resultado
        # volta como seção de reações na própria msg (via evento reaction.message do site).
        site_emoji = await self.bridge.normalize_reaction(str(emoji))
        if site_emoji:
            reactions = await self.bridge.toggle_reaction(cached["site_id"], site_emoji)
            if reactions is not None:
                schedule_reaction_update(self.bridge, cached["site_id"], reactions)
        else:
            logger.info(f"on_raw_reaction_add: emoji {emoji} não é aceito como reação no site")

        if partial:
            with contextlib.suppress(Exception):
                await partial.remove_reaction(emoji, discord.Object(payload.user_id))

    async def setup_hook(self):
        @self.command()
        async def ping(ctx):
            await ctx.send("pong 🏓")

        @self.command()
        async def online(ctx):
            if not self.bridge.online:
                await ctx.send("📭 Ninguém online no chat agora.")
                return
            names = sorted(self.bridge.online.values(), key=str.lower)
            body = "\n".join(f"• `{n}`" for n in names)
            await ctx.send(f"👥 **{len(names)} online**\n{body}")
