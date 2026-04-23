import asyncio
import logging
import os
import time

import config

config.setup()

from bridge import ChatBridge
from site_listener import (
    cookie_health_probe,
    heartbeat,
    initial_backfill,
    message_worker,
    run_websocket,
)
from telegram_handlers import delete_callback, forward_handler, ping, status

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


async def main():
    async with ChatBridge.from_env() as bridge:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        app = Application.builder().token(token).build()
        app.bot_data['bridge'] = bridge
        app.bot_data['start_time'] = time.monotonic()
        app.add_handler(CommandHandler("ping", ping))
        app.add_handler(CommandHandler("status", status))
        app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, forward_handler))
        app.add_handler(CallbackQueryHandler(delete_callback))

        await app.initialize()
        await app.start()
        await initial_backfill(app)

        tasks: list[asyncio.Task] = [
            asyncio.create_task(message_worker(app)),
            asyncio.create_task(run_websocket(app)),
            asyncio.create_task(heartbeat(app)),
            asyncio.create_task(cookie_health_probe(app)),
        ]
        await app.updater.start_polling()
        logger.info("🤖 Bot Rodando (modo WebSocket)...")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("🛑 Shutdown solicitado")
        finally:
            for t in tasks:
                t.cancel()
            try:
                await asyncio.wait_for(bridge.msg_queue.join(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning(f"Shutdown com {bridge.msg_queue.qsize()} msg(s) pendentes")
            try:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()
            except Exception as e:
                logger.warning(f"Erro no shutdown do Telegram: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        logger.error(f"Startup falhou: {e}")
        raise SystemExit(1)
