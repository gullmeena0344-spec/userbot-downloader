import os
import re
import math
import shutil
import subprocess
import asyncio
import base64
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"
SPLIT_SIZE = 1900 * 1024 * 1024

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

def get_codecs(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    v = subprocess.check_output(cmd).decode().strip()

    cmd[3] = "a:0"
    a = subprocess.check_output(cmd).decode().strip()
    return v, a

def process_video(src):
    """
    1) Try fast remux
    2) If codec not h264/aac -> force re-encode
    """
    remuxed = src.rsplit(".", 1)[0] + "_fixed.mp4"

    # Fast remux
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src,
            "-movflags", "+faststart",
            "-map", "0",
            "-c", "copy",
            remuxed
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        v, a = get_codecs(remuxed)
        if v == "h264" and a == "aac":
            os.remove(src)
            return remuxed
    except Exception:
        pass

    # ❌ Codec bad → force re-encode
    encoded = src.rsplit(".", 1)[0] + "_encoded.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src,
            "-map", "0",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            encoded
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    os.remove(src)
    if os.path.exists(remuxed):
        os.remove(remuxed)

    return encoded

def generate_thumb(video):
    thumb = video.rsplit(".", 1)[0] + ".jpg"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video,
            "-ss", "00:00:01",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            thumb
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return thumb if os.path.exists(thumb) else None

def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)

    with open(path, "rb") as f:
        for i in range(count):
            p = f"{path}.part{i+1}.mp4"
            with open(p, "wb") as o:
                o.write(f.read(SPLIT_SIZE))
            parts.append(p)

    os.remove(path)
    return parts

# ================= YT-DLP WITH PROGRESS =================

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

    last = 0
    while True:
        line = await process.stdout.readline()
        if not line:
            break

        text = line.decode(errors="ignore").strip()
        if "[download]" in text and "%" in text:
            now = asyncio.get_event_loop().time()
            if now - last > 1.2:
                last = now
                await status_msg.edit(f"⬇️ **Downloading**\n\n`{text}`")

    if await process.wait() != 0:
        raise Exception("yt-dlp failed")

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = (m.text or "").strip()
    if not url.startswith("http"):
        return

    status = await m.reply("🔍 Detecting video...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        await ytdlp_download(url, status)

        files = collect_files()
        if not files:
            raise Exception("No files downloaded")

        await status.edit("🎬 Processing video...")

        for f in files:
            processed = process_video(f)
            thumb = generate_thumb(processed)

            parts = (
                [processed]
                if os.path.getsize(processed) < SPLIT_SIZE
                else split_file(processed)
            )

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    thumb=thumb,
                    supports_streaming=True,
                    caption=os.path.basename(p),
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

app.run()
