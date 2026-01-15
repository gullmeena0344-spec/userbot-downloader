import os
import re
import math
import shutil
import subprocess
import asyncio
import base64
import requests

from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= COOKIES =================

def ensure_cookies():
    if os.path.exists(COOKIES_FILE):
        return
    data = os.getenv("COOKIES_B64")
    if data:
        with open(COOKIES_FILE, "wb") as f:
            f.write(base64.b64decode(data))

ensure_cookies()

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ================= HELPERS =================

def collect_files():
    return [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))
    ]

def faststart(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-map", "0", "-c", "copy", "-movflags", "+faststart", fixed],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(src)
    return fixed

def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)

    with open(path, "rb") as f:
        for i in range(count):
            part = f"{path}.part{i+1}.mp4"
            with open(part, "wb") as o:
                o.write(f.read(SPLIT_SIZE))
            parts.append(part)

    os.remove(path)
    return parts

# ================= THUMBNAIL =================

def generate_thumb(video):
    thumb = video.rsplit(".", 1)[0] + ".jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-i", video, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return thumb if os.path.exists(thumb) else None

# ================= ARIA2 =================

def aria2_download(url):
    cmd = [
        "aria2c",
        "-x", "8",
        "-s", "8",
        "-k", "1M",
        "--file-allocation=trunc",
        "-d", DOWNLOAD_DIR,
        url
    ]
    subprocess.run(cmd, check=True)

# ================= GOFILE (REALISTIC) =================

def is_gofile(url):
    return "gofile.io" in url

# ================= YT-DLP (UNCHANGED) =================

async def ytdlp_download(url, status_msg):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    last_edit = 0
    while True:
        line = await process.stdout.readline()
        if not line:
            break

        text = line.decode(errors="ignore").strip()
        if "[download]" in text and "%" in text:
            now = asyncio.get_event_loop().time()
            if now - last_edit > 1.2:
                last_edit = now
                await status_msg.edit(f"⬇️ Downloading\n`{text}`")

    if await process.wait() != 0:
        raise Exception("yt-dlp failed")

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = (m.text or "").strip()
    if not url.startswith("http"):
        return

    status = await m.reply("🔍 Detecting link...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # ---- GOFILE → ARIA2 ONLY ----
        if is_gofile(url):
            await status.edit("⬇️ Downloading via aria2...")
            aria2_download(url)

        # ---- EVERYTHING ELSE ----
        else:
            await ytdlp_download(url, status)

        files = collect_files()
        if not files:
            raise Exception("No files downloaded")

        await status.edit("📦 Processing...")

        for f in files:
            fixed = faststart(f)
            thumb = generate_thumb(fixed)

            parts = [fixed] if os.path.getsize(fixed) < SPLIT_SIZE else split_file(fixed)

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    thumb=thumb,
                    supports_streaming=True,
                    caption=os.path.basename(p)
                )
                os.remove(p)

            if thumb and os.path.exists(thumb):
                os.remove(thumb)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= RUN =================

app.run()
