import os
import re
import math
import shutil
import subprocess
import asyncio
import base64

import cloudscraper
from bs4 import BeautifulSoup

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
    try:
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            video
        ]).decode().strip())
        seek = max(1, int(duration // 2))
    except Exception:
        seek = 1

    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(seek), "-i", video,
         "-vframes", "1", "-vf",
         "scale=320:320:force_original_aspect_ratio=decrease",
         "-q:v", "5", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if not os.path.exists(thumb) or os.path.getsize(thumb) > 200 * 1024:
        if os.path.exists(thumb):
            os.remove(thumb)
        return None

    return thumb

# ================= GOFILE =================

def is_gofile(url):
    return "gofile.io/d/" in url

def scrape_gofile(url):
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )
    r = scraper.get(url, timeout=30)
    if r.status_code != 200:
        raise Exception(f"GoFile HTTP {r.status_code}")

    soup = BeautifulSoup(r.text, "html.parser")
    files = []

    for script in soup.find_all("script"):
        if script.string and "directLink" in script.string:
            names = re.findall(r'"name":"(.*?)"', script.string)
            links = re.findall(r'"directLink":"(https:\\/\\/.*?)"', script.string)
            for n, l in zip(names, links):
                files.append((n, l.replace("\\/", "/")))

    if not files:
        raise Exception("Scrape failed")

    return files

# ================= ARIA2 WITH PROGRESS =================

async def aria2_download(url, status_msg):
    cmd = [
        "aria2c",
        "--summary-interval=1",
        "--file-allocation=trunc",
        "--dir", DOWNLOAD_DIR,
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
            now = asyncio.get_event_loop().time()
            if now - last > 1.2:
                last = now
                await status_msg.edit(f"⬇️ **aria2**\n\n`{text}`")

    if await proc.wait() != 0:
        raise Exception("aria2 failed")

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
                await status_msg.edit(f"⬇️ **Downloading**\n\n`{text}`")

    if await process.wait() != 0:
        raise Exception("yt-dlp failed")

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = (m.text or "").strip()
    if not url.startswith("http"):
        return

    status = await m.reply("🔍 Detecting...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # ---------- GOFILE PIPELINE ----------
        if is_gofile(url):
            jd = shutil.which("jdownloader") or shutil.which("jd-cli")

            if jd:
                await status.edit("⬇️ **JDownloader**")
                subprocess.run([jd, "-d", DOWNLOAD_DIR, url], check=True)

            else:
                try:
                    await status.edit("⬇️ **aria2**")
                    await aria2_download(url, status)
                except Exception:
                    files = scrape_gofile(url)
                    for name, link in files:
                        subprocess.run(
                            ["curl", "-L", "--fail", link, "-o",
                             os.path.join(DOWNLOAD_DIR, name)],
                            check=True
                        )

        # ---------- EVERYTHING ELSE ----------
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

# ================= RUN =================

app.run()
