import os
import math
import shutil
import subprocess
import asyncio
import base64
import time

from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9 GB

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

# ---------- SAFE FASTSTART ----------

def faststart(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src,
            "-map", "0",
            "-c", "copy",
            "-movflags", "+faststart",
            fixed
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if os.path.exists(fixed) and os.path.getsize(fixed) > 0:
        os.remove(src)
        return fixed
    else:
        if os.path.exists(fixed):
            os.remove(fixed)
        return src

# ---------- SAFE MP4 SPLIT (NO BLUE SCREEN) ----------

def split_mp4_ffmpeg(path):
    base = path.rsplit(".", 1)[0]
    out_pattern = f"{base}_part%03d.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", path,
            "-c", "copy",
            "-map", "0",
            "-f", "segment",
            "-segment_time", "1800",   # ~30 min
            "-reset_timestamps", "1",
            out_pattern
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    parts = sorted(
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if f.startswith(os.path.basename(base)) and "_part" in f
    )

    if parts:
        os.remove(path)

    return parts

# ---------- THUMBNAIL ----------

def generate_thumb(video):
    thumb = video.rsplit(".", 1)[0] + ".jpg"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", "5",
            "-i", video,
            "-vframes", "1",
            "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
            "-q:v", "5",
            thumb
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if os.path.exists(thumb) and os.path.getsize(thumb) < 200 * 1024:
        return thumb

    if os.path.exists(thumb):
        os.remove(thumb)
    return None

# ================= DOWNLOADERS =================

# ---------- yt-dlp with progress ----------

async def ytdlp_download(url, status):
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

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    last = 0
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode(errors="ignore").strip()
        if "[download]" in text and "%" in text:
            now = time.time()
            if now - last > 1.2:
                last = now
                await status.edit(f"⬇️ Downloading\n`{text}`")

    if await proc.wait() != 0:
        raise Exception("yt-dlp failed")

# ---------- aria2 fallback with progress ----------

async def aria2_download(url, status):
    cmd = [
        "aria2c",
        "--summary-interval=1",
        "-x", "8",
        "-s", "8",
        "-k", "1M",
        "-d", DOWNLOAD_DIR,
        url
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    last = 0
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode(errors="ignore").strip()
        if "%" in text:
            now = time.time()
            if now - last > 1.2:
                last = now
                await status.edit(f"⬇️ Downloading\n`{text}`")

    if await proc.wait() != 0:
        raise Exception("aria2 failed")

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

        # ---------- DOWNLOAD ----------
        try:
            await ytdlp_download(url, status)
        except Exception:
            await aria2_download(url, status)

        files = collect_files()
        if not files:
            raise Exception("No files downloaded")

        await status.edit("📦 Processing video...")

        # ---------- PROCESS & UPLOAD ----------
        for f in files:
            fixed = faststart(f)

            if os.path.getsize(fixed) < SPLIT_SIZE:
                parts = [fixed]
            else:
                parts = split_mp4_ffmpeg(fixed)

            total = len(parts)

            for i, p in enumerate(parts, start=1):
                thumb = generate_thumb(p)
                caption = f"{os.path.basename(p)}\n({i}/{total})"

                last = 0

                async def progress(current, total_size):
                    nonlocal last
                    now = time.time()
                    if now - last > 1.2:
                        last = now
                        percent = current * 100 / total_size
                        await status.edit(
                            f"⬆️ Uploading {i}/{total}\n"
                            f"{percent:.1f}%"
                        )

                await app.send_video(
                    "me",
                    video=p,
                    thumb=thumb,
                    supports_streaming=True,
                    caption=caption,
                    progress=progress
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
