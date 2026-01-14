import os
import re
import asyncio
import time
import math
import subprocess
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= UTILITIES =================

async def safe_edit(msg: Message, text: str):
    try:
        await msg.edit(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except:
        pass


def sizeof_fmt(num):
    for unit in ["B","KB","MB","GB","TB"]:
        if num < 1024:
            return f"{num:.2f}{unit}"
        num /= 1024


def progress_bar(done, total):
    if total == 0:
        return "▰▰▰▰▰▰▰▰▰▰ 0%"
    percent = done * 100 / total
    filled = int(percent / 10)
    return "▰" * filled + "▱" * (10 - filled) + f" {percent:.1f}%"


# ================= YT-DLP DOWNLOAD =================

async def download_ytdlp(url, status):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0",
        "--referer", referer,

        # 🔥 FIX FOR cdnsolutions.media / AV1 HLS
        "--downloader", "ffmpeg",
        "--hls-use-mpegts",
        "--hls-prefer-ffmpeg",
        "--no-hls-rewrite",
        "--no-part",

        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    last = time.time()

    async for line in proc.stdout:
        line = line.decode(errors="ignore")
        if "[download]" in line and "%" in line:
            if time.time() - last > 2:
                await safe_edit(status, f"⬇️ {line.strip()}")
                last = time.time()

    code = await proc.wait()
    if code != 0:
        raise Exception("yt-dlp failed")

    files = sorted(
        [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)],
        key=os.path.getmtime
    )
    return files[-1]


# ================= THUMBNAIL =================

def generate_thumb(video):
    thumb = video + ".jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-i", video, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return thumb if os.path.exists(thumb) else None


# ================= UPLOAD =================

async def upload_video(path, status):
    size = os.path.getsize(path)
    thumb = generate_thumb(path)

    sent = 0
    start = time.time()

    async def progress(current, total):
        nonlocal sent
        sent = current
        speed = current / max(1, time.time() - start)
        bar = progress_bar(current, total)
        await safe_edit(
            status,
            f"⬆️ Uploading\n{bar}\n{sizeof_fmt(current)} / {sizeof_fmt(total)}\n⚡ {sizeof_fmt(speed)}/s"
        )

    await app.send_video(
        "me",
        path,
        thumb=thumb,
        progress=progress
    )

    if thumb:
        os.remove(thumb)
    os.remove(path)


# ================= MESSAGE HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, message: Message):
    url = message.text.strip()

    if not url.startswith("http"):
        return

    status = await message.reply("🔍 Processing...")

    try:
        video = await download_ytdlp(url, status)
        await upload_video(video, status)
        await safe_edit(status, "✅ Done")
    except Exception as e:
        await safe_edit(status, f"❌ Error:\n{e}")


# ================= START =================

print("Userbot started")
app.run()
