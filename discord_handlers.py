import contextlib
import logging
import os

import discord
from discord.ext import commands

from bridge import ChatBridge
from formatting import build_bbcode_payload
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

        if message.attachments and not self.bridge.imgbb_key:
            logger.warning("Anexo detectado no Discord, mas IMGBB_API_KEY não está configurada.")

        if message.attachments:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
                    try:
                        img_bytes = await attachment.read()
                        img_url = await self.bridge.upload_to_imgbb(img_bytes, ephemeral=True, filename=attachment.filename)
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
                    img_url = await self.bridge.upload_to_imgbb(data, ephemeral=True, filename=f"sticker.{ext}")
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

    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return

        if str(reaction.emoji) != "🗑️":
            return

        msg_id = reaction.message.id
        if msg_id in self.bridge.msg_map:
            cached = self.bridge.msg_map[msg_id]

            if await self.bridge.delete_message(cached["site_id"]):
                try:
                    await reaction.message.delete()
                except Exception as e:
                    logger.warning(f"Erro ao deletar msg no Discord: {e}")
            else:
                with contextlib.suppress(BaseException):
                    await reaction.remove(user)

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
