import os
import re
import asyncio
import time
import shutil
import subprocess
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

if not API_ID or not API_HASH or not SESSION_STRING:
    raise RuntimeError("Missing API_ID / API_HASH / SESSION_STRING")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# =========================================


def clean_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


async def safe_edit(msg: Message, text: str):
    try:
        await msg.edit(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await msg.edit(text)
    except Exception:
        pass


# ================= yt-dlp =================

async def download_ytdlp(url: str, status: Message):
    output = str(DOWNLOAD_DIR / "%(title).80s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "--downloader", "ffmpeg",
        "--hls-use-mpegts",
        "--no-hls-rewrite",
        "-o", output,
        url
    ]

    await safe_edit(status, "⬇️ Downloading…")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    last_update = 0
    async for line in proc.stdout:
        line = line.decode(errors="ignore").strip()
        if "[download]" in line and "%" in line:
            if time.time() - last_update > 2:
                await safe_edit(status, f"⬇️ {line}")
                last_update = time.time()

    code = await proc.wait()
    if code != 0:
        raise Exception("yt-dlp failed")

    video = None
    thumb = None

    for f in DOWNLOAD_DIR.iterdir():
        if f.suffix == ".mp4":
            video = f
        elif f.suffix == ".jpg":
            thumb = f

    if not video:
        raise Exception("No video file found")

    return video, thumb


# ================= Upload =================

async def upload_video(app: Client, msg: Message, video: Path, thumb: Path | None):
    total = video.stat().st_size

    async def progress(current, total_bytes):
        percent = current * 100 / total_bytes
        await safe_edit(
            msg,
            f"⬆️ Uploading… {percent:.1f}%\n"
            f"{current/1024/1024:.1f} MB / {total_bytes/1024/1024:.1f} MB"
        )

    await app.send_video(
        chat_id=msg.chat.id,
        video=str(video),
        thumb=str(thumb) if thumb and thumb.exists() else None,
        supports_streaming=True,
        progress=progress
    )


# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)


# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(client: Client, message: Message):
    url = message.text.strip()
    if not url.startswith("http"):
        return

    status = await message.reply("⏳ Processing…")

    try:
        video, thumb = await download_ytdlp(url, status)
        await upload_video(client, status, video, thumb)
        await safe_edit(status, "✅ Done")
    except Exception as e:
        await safe_edit(status, f"❌ Error:\n{e}")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        DOWNLOAD_DIR.mkdir(exist_ok=True)


print("✅ Userbot started (STREAMING MODE)")
app.run()
