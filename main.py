import asyncio
import logging
import os
import time

import config

config.setup()

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bridge import ChatBridge
from config import settings
from discord_handlers import DiscordBot
from site_listener import (
    cookie_health_probe,
    heartbeat,
    initial_backfill,
    message_worker,
    run_websocket,
)
from telegram_handlers import (
    delete_callback,
    forward_handler,
    online_cmd,
    ping,
    status,
)

logger = logging.getLogger(__name__)


async def main():
    async with ChatBridge.from_env() as bridge:
        app = None
        if settings.enable_telegram:
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if token:
                app = Application.builder().token(token).build()
                app.bot_data["bridge"] = bridge
                app.bot_data["start_time"] = time.monotonic()
                app.add_handler(CommandHandler("ping", ping))
                app.add_handler(CommandHandler("status", status))
                app.add_handler(CommandHandler("online", online_cmd))
                app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, forward_handler))
                app.add_handler(CallbackQueryHandler(delete_callback))

                await app.initialize()
                await app.start()
            else:
                logger.warning("TELEGRAM_BOT_TOKEN não configurado, pulando Telegram.")

        await initial_backfill(bridge)

        ds_bot = None
        tasks: list[asyncio.Task] = []
        if settings.enable_discord:
            ds_token = os.getenv("DISCORD_BOT_TOKEN")
            if ds_token:
                ds_bot = DiscordBot(bridge)
                tasks.append(asyncio.create_task(ds_bot.start(ds_token)))
            else:
                logger.warning("DISCORD_BOT_TOKEN não configurado, pulando Discord.")

        tasks.extend([
            asyncio.create_task(message_worker(bridge, app, ds_bot)),
            asyncio.create_task(run_websocket(bridge, app)),
            asyncio.create_task(heartbeat(bridge)),
            asyncio.create_task(cookie_health_probe(bridge, app)),
        ])

        if settings.enable_telegram:
            await app.updater.start_polling()
            logger.info("🤖 Bot Telegram Rodando...")

        if ds_bot:
            logger.info("🤖 Bot Discord Rodando...")

        logger.info("🚀 Unitedgram iniciado (modo WebSocket)...")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("🛑 Shutdown solicitado")
        finally:
            for t in tasks:
                t.cancel()
            try:
                await asyncio.wait_for(bridge.msg_queue.join(), timeout=5)
            except TimeoutError:
                logger.warning(f"Shutdown com {bridge.msg_queue.qsize()} msg(s) pendentes")
            try:
                if settings.enable_telegram:
                    await app.updater.stop()
                    await app.stop()
                    await app.shutdown()
                if ds_bot:
                    await ds_bot.close()
            except Exception as e:
                logger.warning(f"Erro no shutdown dos bots: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        logger.error(f"Startup falhou: {e}")
        raise SystemExit(1)
