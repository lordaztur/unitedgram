import argparse
import asyncio
import logging
import os
import time
from pathlib import Path

import config

# Resolver os caminhos padrão e do arg -tk a partir daqui, e não do diretório atual,
# para que funcionem mesmo que o bot seja iniciado de # outro lugar (ex.: systemd, cron).
# Para os args --env e --cookies deixei o path todo porque me parece mais
# lógico que é para apontar para um arquivo específico ao invés de relativo
BASE_DIR = Path(__file__).resolve().parent


def _parse_args(argv: "list[str] | None" = None) -> argparse.Namespace:
    """Lê os argumentos de linha de comando do bot."""
    parser = argparse.ArgumentParser(
        prog="unitedgram",
        description="Ponte de sincronização WebSocket <-> Telegram/Discord.",
    )
    parser.add_argument(
        "--env",
        dest="env_file",
        metavar="ARQUIVO",
        default=None,
        help="Caminho do arquivo .env (padrão: .env). "
             "Tem prioridade sobre -tk para o arquivo de ambiente.",
    )
    parser.add_argument(
        "--cookies", "--cookie",
        dest="cookies_file",
        metavar="ARQUIVO",
        default=None,
        help="Caminho do arquivo de cookies no formato Netscape "
             "(padrão: cookies/cookies.txt). Tem prioridade sobre -tk para os cookies.",
    )
    parser.add_argument(
        "-tk", "--tracker",
        dest="tk",
        metavar="NOME",
        default=None,
        help="Atalho: carrega .NOME.env e cookies/cookies.NOME.txt de uma vez. "
             "Um --env/--cookies explícito ainda tem prioridade sobre este atalho.",
    )
    return parser.parse_args(argv)


def _resolve_config_paths(args: argparse.Namespace) -> "tuple[Path, Path]":
    """Decide quais arquivos .env e cookies usar.

    Precedência (avaliada por arquivo, de forma independente):
        --env / --cookies explícito  >  atalho -tk  >  padrão
    Por ser por arquivo, é válido combinar -tk com apenas um override
    (ex.: `-tk cba --env outro.env` usa outro.env mas mantém os cookies do cba).
    """
    if args.env_file is not None:
        env_path = Path(args.env_file).expanduser()
    elif args.tk:
        env_path = BASE_DIR / f".{args.tk}.env"
    else:
        env_path = BASE_DIR / ".env"

    if args.cookies_file is not None:
        cookies_path = Path(args.cookies_file).expanduser()
    elif args.tk:
        cookies_path = BASE_DIR / "cookies" / f"cookies.{args.tk}.txt"
    else:
        cookies_path = BASE_DIR / "cookies" / "cookies.txt"

    return env_path, cookies_path


_args = _parse_args()
_env_path, _cookies_path = _resolve_config_paths(_args)

# config.setup() configura o logging e carrega o .env escolhido em os.environ
# de onde todo o restante do código lê as variáveis de configuração.
config.setup(env_path=_env_path)

logger = logging.getLogger(__name__)
logger.info("Configuração: env=%s | cookies=%s", _env_path, _cookies_path)

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    MessageReactionHandler,
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
    reaction_handler,
    status,
)


async def main():
    async with ChatBridge.from_env(cookies_path=_cookies_path) as bridge:
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
                app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.Sticker.ALL | filters.ANIMATION) & ~filters.COMMAND, forward_handler))
                app.add_handler(CallbackQueryHandler(delete_callback))
                app.add_handler(MessageReactionHandler(reaction_handler))

                await app.initialize()
                await app.start()
            else:
                logger.warning("TELEGRAM_BOT_TOKEN não configurado, pulando Telegram.")
        bridge.telegram_app = app

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
        bridge.discord_bot = ds_bot

        tasks.extend([
            asyncio.create_task(message_worker(bridge, app, ds_bot)),
            asyncio.create_task(run_websocket(bridge, app)),
            asyncio.create_task(heartbeat(bridge)),
            asyncio.create_task(cookie_health_probe(bridge, app)),
        ])

        if settings.enable_telegram:
            # message_reaction não vem por padrão; precisa pedir explicitamente.
            await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
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
