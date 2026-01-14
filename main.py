import os
import re
import math
import shutil
import subprocess
import requests
import base64
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB
COOKIES_FILE = "cookies.txt"

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
BUNKR_RE = re.compile(r"https?://(www\.)?bunkr\.(cr|pk|fi|ru)/")

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

def collect_files(root):
    out = []
    for base, _, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            if p.lower().endswith(ALLOWED_EXT):
                out.append(p)
    return out

# ---------- PIXELDRAIN ----------

def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

# ---------- MEGA (FIXED: mega-get) ----------

def download_mega(url):
    env = os.environ.copy()
    env["HOME"] = "/root"  # REQUIRED inside Docker

    cmd = [
        "mega-get",
        "--ignore-quota-warn",
        "--recursive",
        url,
        DOWNLOAD_DIR
    ]

    subprocess.run(cmd, check=True, env=env)

# ---------- YT-DLP ----------

def download_ytdlp(url, out):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/best",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "--referer", referer,
        "--add-header", f"Origin:{referer}",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", out,
        url
    ]

    subprocess.run(cmd, check=True)

# ---------- FIX STREAMING + THUMB ----------

def faststart_and_thumb(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    thumb = src.rsplit(".", 1)[0] + ".jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    os.remove(src)
    return fixed, thumb

# ---------- SPLIT >2GB ----------

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

# ================= USERBOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Processing link...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # ❌ Bunkr
        if BUNKR_RE.search(url):
            await status.edit("❌ Bunkr is blocked on Railway")
            return

        # Pixeldrain
        if (px := PIXELDRAIN_RE.search(url)):
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()

            path = os.path.join(DOWNLOAD_DIR, info["name"])
            await status.edit("⬇️ Downloading from Pixeldrain...")
            download_pixeldrain(fid, path)

        # MEGA
        elif MEGA_RE.search(url):
            await status.edit("⬇️ Downloading from MEGA (folders supported)...")
            download_mega(url)

        # yt-dlp
        else:
            await status.edit("🎥 Downloading video...")
            out = os.path.join(DOWNLOAD_DIR, "%(title).80s.%(ext)s")
            download_ytdlp(url, out)

        files = collect_files(DOWNLOAD_DIR)
        if not files:
            raise Exception("No video files found")

        await status.edit(f"📦 Uploading {len(files)} file(s)...")

        for f in files:
            fixed, thumb = faststart_and_thumb(f)

            parts = (
                [fixed]
                if os.path.getsize(fixed) < SPLIT_SIZE
                else split_file(fixed)
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

            if os.path.exists(thumb):
                os.remove(thumb)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
