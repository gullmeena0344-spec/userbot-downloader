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
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"

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

def is_direct_video(url):
    return url.lower().split("?")[0].endswith(
        (".mp4", ".mkv", ".webm", ".avi", ".mov")
    )

def is_hls(url):
    return ".m3u8" in url.lower()

# ---------- ARIA2 ----------
def download_aria2(url, out):
    cmd = [
        "aria2c",
        "-x", "1",
        "-s", "1",
        "-k", "1M",
        "--timeout=20",
        "--connect-timeout=20",
        "--file-allocation=trunc",
        "--header=User-Agent: Mozilla/5.0",
        "--header=Accept:*/*",
        "-o", out,
        url
    ]
    subprocess.run(cmd, check=True)

# ---------- DIRECT FALLBACK ----------
def download_direct(url, path):
    r = requests.get(url, stream=True, timeout=(10, 30))
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

# ---------- PIXELDRAIN ----------
def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

# ---------- MEGA ----------
def download_mega(url):
    cmd = [
        "megadl",
        "--path", DOWNLOAD_DIR,
        url
    ]
    subprocess.run(cmd, check=True)

# ---------- YT-DLP ----------
def download_ytdlp(url, out):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--downloader", "aria2c",
        "--downloader-args", "aria2c:-x 1 -s 1 -k 1M",
        "--user-agent", "Mozilla/5.0",
        "--add-header", f"Referer:{referer}",
        "--add-header", f"Origin:{referer}",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]
    subprocess.run(cmd, check=True)

# ---------- CONVERT ----------
def convert_mp4(src):
    dst = src.rsplit(".", 1)[0] + ".mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(src)
    return dst

# ---------- SPLIT ----------
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

# ================= BOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Processing link...")

    try:
        files = []

        # ❌ BUNKR
        if BUNKR_RE.search(url):
            await status.edit(
                "❌ **Bunkr blocked on Railway**\n"
                "Run bot locally to download bunkr."
            )
            return

        # MEGA
        if MEGA_RE.search(url):
            await status.edit("⬇️ Downloading from MEGA...")
            download_mega(url)
            files.extend(
                os.path.join(DOWNLOAD_DIR, f)
                for f in os.listdir(DOWNLOAD_DIR)
            )

        # PIXELDRAIN
        elif (px := PIXELDRAIN_RE.search(url)):
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()
            path = os.path.join(DOWNLOAD_DIR, info["name"])
            await status.edit("⬇️ Pixeldrain downloading...")
            download_pixeldrain(fid, path)
            files.append(path)

        # DIRECT MP4
        elif is_direct_video(url):
            name = url.split("/")[-1].split("?")[0]
            path = os.path.join(DOWNLOAD_DIR, name)
            await status.edit("⚡ Direct download...")
            try:
                download_aria2(url, path)
            except Exception:
                download_direct(url, path)
            files.append(path)

        # HLS / OTHER
        else:
            await status.edit("🎥 Extracting video...")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)
            files.extend(
                os.path.join(DOWNLOAD_DIR, f)
                for f in os.listdir(DOWNLOAD_DIR)
            )

        # UPLOAD
        for f in files:
            path = f
            if not path.lower().endswith(".mp4"):
                path = convert_mp4(path)

            parts = (
                [path]
                if os.path.getsize(path) < SPLIT_SIZE
                else split_file(path)
            )

            for p in parts:
                await m.reply_video(
                    video=p,
                    supports_streaming=True,
                    caption=os.path.basename(p),
                )
                os.remove(p)

        await status.edit("✅ Done & cleaned")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
