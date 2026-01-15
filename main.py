import os, re, math, shutil, subprocess, time
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
UA = "Mozilla/5.0"
ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".jpg", ".png")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MEGA_RE = re.compile(r"https?://mega\.nz/")
GO_RE = re.compile(r"https?://")

# ================= PROGRESS =================

async def simple_progress(current, total, msg, tag):
    if total == 0:
        return
    pct = (current / total) * 100
    bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
    try:
        await msg.edit(f"**{tag}**\n{bar}")
    except:
        pass

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    sleep_threshold=60
)

# ================= HELPERS =================

def extract_url(text):
    m = re.search(r"(https?://[^\s]+)", text)
    return m.group(1) if m else None

# ================= MEGA DOWNLOADER =================

async def download_mega(url, status):
    cmd = [
        "megadl",
        "--no-progress",
        "--path", DOWNLOAD_DIR,
        url
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in proc.stdout:
        if "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
                await status.edit(f"**Downloading (MEGA)**\n{bar}")
            except:
                pass

    proc.wait()

# ================= YT-DLP (ARIA2) =================

def download_ytdlp(url):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    subprocess.run([
        "yt-dlp",
        "--no-playlist",
        "--external-downloader", "aria2c",
        "--external-downloader-args", "-x 16 -k 1M",
        "-o", out,
        url
    ], check=True)

# ================= VIDEO FIX + THUMB =================

def faststart_and_thumb(src):
    base = src.rsplit(".", 1)[0]
    fixed = f"{base}_fixed.mp4"
    thumb = f"{base}.jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:40", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    os.remove(src)
    return fixed, thumb if os.path.exists(thumb) else None

# ================= SPLIT =================

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

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(client, m: Message):
    url = extract_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Starting download...")

    if MEGA_RE.search(url):
        await download_mega(url, status)
    else:
        download_ytdlp(url)

    await status.edit("🎞 Processing...")

    for f in os.listdir(DOWNLOAD_DIR):
        p = os.path.join(DOWNLOAD_DIR, f)

        if not p.lower().endswith(ALLOWED_EXT):
            continue

        if p.lower().endswith((".jpg", ".png")):
            await client.send_photo("me", p)
            os.remove(p)
            continue

        fixed, thumb = faststart_and_thumb(p)
        parts = [fixed]

        if os.path.getsize(fixed) > SPLIT_SIZE:
            parts = split_file(fixed)

        for part in parts:
            await client.send_video(
                "me",
                video=part,
                thumb=thumb,
                supports_streaming=True,
                progress=simple_progress,
                progress_args=("Uploading",)
            )
            os.remove(part)

        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    await status.edit("✅ Done")

# ==========
