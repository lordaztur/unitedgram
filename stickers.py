from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageSequence

logger = logging.getLogger(__name__)

STICKER_CACHE_DIR = Path(__file__).parent / "stickers"
STICKER_CACHE_DIR.mkdir(exist_ok=True)


def sticker_bbcode(url: str) -> str:
    from config import settings
    w = settings.sticker_img_width
    if w > 0:
        return f"[img={w}]{url}[/img]"
    return f"[img]{url}[/img]"

MAX_VIDEO_FRAMES = 60
VIDEO_TARGET_FPS = 15
_CACHE_EXTS = ("gif", "png", "webp")


def _cached(platform: str, unique_id: str) -> Optional[tuple[bytes, str]]:
    for ext in _CACHE_EXTS:
        p = STICKER_CACHE_DIR / f"{platform}_{unique_id}.{ext}"
        if p.exists():
            return p.read_bytes(), ext
    return None


def _save_cache(platform: str, unique_id: str, data: bytes, ext: str) -> None:
    p = STICKER_CACHE_DIR / f"{platform}_{unique_id}.{ext}"
    tmp = p.with_suffix(f".{ext}.tmp")
    tmp.write_bytes(data)
    tmp.replace(p)


def _render_lottie_to_gif(raw_bytes: bytes) -> bytes:
    from lottie.exporters.gif import export_gif
    from lottie.parsers.tgs import parse_tgs

    src = io.BytesIO(raw_bytes)
    animation = parse_tgs(src)
    out = io.BytesIO()
    export_gif(animation, out, skip_frames=2)
    return out.getvalue()


def _render_webm_to_gif(raw_bytes: bytes) -> bytes:
    import imageio.v3 as iio

    frames_np = iio.imread(io.BytesIO(raw_bytes), plugin="FFMPEG", extension=".webm")
    if frames_np.ndim == 3:
        frames_np = frames_np[None, ...]

    total = frames_np.shape[0]
    step = max(1, total // MAX_VIDEO_FRAMES) if total > MAX_VIDEO_FRAMES else 1
    frames = [Image.fromarray(frames_np[i]).convert("RGBA") for i in range(0, total, step)]

    if not frames:
        raise ValueError("WebM sem frames")

    out = io.BytesIO()
    duration = int(1000 / VIDEO_TARGET_FPS)
    frames[0].save(
        out,
        format="GIF",
        append_images=frames[1:],
        save_all=True,
        duration=duration,
        loop=0,
        disposal=2,
    )
    return out.getvalue()


def _apng_to_gif(raw_bytes: bytes) -> bytes:
    im = Image.open(io.BytesIO(raw_bytes))
    frames = [f.convert("RGBA") for f in ImageSequence.Iterator(im)]
    if not frames:
        raise ValueError("APNG sem frames")
    if len(frames) == 1:
        out = io.BytesIO()
        frames[0].save(out, format="PNG")
        return out.getvalue()

    duration = im.info.get("duration", 100) or 100
    out = io.BytesIO()
    frames[0].save(
        out,
        format="GIF",
        append_images=frames[1:],
        save_all=True,
        duration=duration,
        loop=0,
        disposal=2,
    )
    return out.getvalue()


async def process_telegram_sticker(sticker, bot) -> Optional[tuple[bytes, str]]:
    unique_id = sticker.file_unique_id
    if (hit := _cached("tg", unique_id)) is not None:
        return hit

    try:
        file_obj = await bot.get_file(sticker.file_id)
        raw = bytes(await file_obj.download_as_bytearray())
    except Exception as e:
        logger.warning(f"sticker(tg/{unique_id}): falha no download: {e}")
        return None

    try:
        if sticker.is_animated:
            data = await asyncio.to_thread(_render_lottie_to_gif, raw)
            ext = "gif"
        elif sticker.is_video:
            data = await asyncio.to_thread(_render_webm_to_gif, raw)
            ext = "gif"
        else:
            data = raw
            ext = "webp"
    except Exception as e:
        logger.warning(f"sticker(tg/{unique_id}): falha no render ({_tg_kind(sticker)}): {e}")
        return None

    _save_cache("tg", unique_id, data, ext)
    return data, ext


def _tg_kind(sticker) -> str:
    if sticker.is_animated:
        return "tgs/lottie"
    if sticker.is_video:
        return "webm"
    return "webp"


async def process_discord_sticker(sticker_item, http_client) -> Optional[tuple[bytes, str]]:
    import discord

    unique_id = str(sticker_item.id)
    if (hit := _cached("dc", unique_id)) is not None:
        return hit

    try:
        resp = await http_client.get(sticker_item.url)
        if resp.status_code != 200:
            logger.warning(f"sticker(dc/{unique_id}): HTTP {resp.status_code}")
            return None
        raw = resp.content
    except Exception as e:
        logger.warning(f"sticker(dc/{unique_id}): falha no download: {e}")
        return None

    try:
        fmt = sticker_item.format
        if fmt == discord.StickerFormatType.lottie:
            data = await asyncio.to_thread(_render_lottie_to_gif, raw)
            ext = "gif"
        elif fmt == discord.StickerFormatType.apng:
            data = await asyncio.to_thread(_apng_to_gif, raw)
            ext = "gif"
        elif fmt == discord.StickerFormatType.gif:
            data = raw
            ext = "gif"
        else:
            data = raw
            ext = "png"
    except Exception as e:
        logger.warning(f"sticker(dc/{unique_id}): falha no render ({sticker_item.format}): {e}")
        return None

    _save_cache("dc", unique_id, data, ext)
    return data, ext
