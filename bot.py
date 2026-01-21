import os
import asyncio
import shutil
import subprocess
import logging
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

WORKDIR = Path("downloads")
MAX_TG_SIZE = 1990 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("YTDLP-BOT")

app = Client(
    "ytdlp-aria-bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID,
    api_hash=API_HASH
)

def faststart(src):
    out = src + ".fast.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-c", "copy", "-movflags", "+faststart", out],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return out

def make_thumb(src):
    thumb = src + ".jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return thumb if os.path.exists(thumb) else None

def split_2gb(src):
    size = os.path.getsize(src)
    if size <= MAX_TG_SIZE:
        return [src]

    base = src.replace(".mp4", "")
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", src,
            "-c", "copy", "-map", "0",
            "-f", "segment",
            "-segment_time", "3600",
            "-reset_timestamps", "1",
            f"{base}_part_%03d.mp4"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    return sorted(str(p) for p in Path(".").glob(base + "_part_*.mp4"))

async def run_ytdlp(url, out):
    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
        "--external-downloader", "aria2c",
        "--external-downloader-args", "-x 16 -k 1M",
        "-o", out,
        url
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()

@app.on_message(filters.private & filters.text)
async def handler(client, message: Message):
    url = message.text.strip()
    if not url.startswith("http"):
        return

    WORKDIR.mkdir(exist_ok=True)
    os.chdir(WORKDIR)

    status = await message.reply("⬇️ Downloading...")

    try:
        await run_ytdlp(url, "video.%(ext)s")

        mp4s = list(Path(".").glob("*.mp4"))
        if not mp4s:
            await status.edit("❌ Download failed")
            return

        video = str(mp4s[0])
        fixed = faststart(video)
        thumb = make_thumb(fixed)
        parts = split_2gb(fixed)

        for i, part in enumerate(parts, 1):
            caption = os.path.basename(video)
            if len(parts) > 1:
                caption += f" [Part {i}/{len(parts)}]"

            await client.send_video(
                chat_id=message.chat.id,
                video=part,
                caption=caption,
                supports_streaming=True,
                thumb=thumb
            )

        await status.edit("✅ Done")

    except Exception as e:
        log.error(e)
        await status.edit("❌ Error")

    finally:
        os.chdir("..")
        shutil.rmtree(WORKDIR, ignore_errors=True)

app.run()
