import os, re, shutil, subprocess, requests, time
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN")

CHANNEL_ID = -1003609000029  # ✅ YOUR CHANNEL (important: -100)

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= CLEANUP =================

def cleanup():
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= PROGRESS =================

async def upload_progress(current, total, msg):
    if total == 0:
        return
    pct = current * 100 / total
    bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
    try:
        await msg.edit(f"⬆️ Uploading\n{bar}")
    except:
        pass

# ================= HELPERS =================

def extract_url(text):
    m = re.search(r"(https?://[^\s]+)", text)
    return m.group(1) if m else None

# ================= GOFILE =================

async def download_gofile(cid, status):
    r = requests.get(
        f"https://api.gofile.io/getContent?contentId={cid}",
        headers={"Authorization": f"Bearer {GOFILE_API_TOKEN}"}
    ).json()

    for f in r["data"]["children"].values():
        if f["type"] != "file":
            continue

        out = os.path.join(DOWNLOAD_DIR, f["name"])
        with requests.get(f["directLink"], stream=True) as d:
            with open(out, "wb") as o:
                for c in d.iter_content(1024 * 1024):
                    o.write(c)

# ================= YT-DLP =================

async def download_ytdlp(url, status):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", UA,
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]

    subprocess.run(cmd, check=True)

# ================= VIDEO FIX =================

def fix_video(src):
    base = src.rsplit(".", 1)[0]
    fixed = f"{base}_fixed.mp4"
    thumb = f"{base}.jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:05", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    os.remove(src)
    return fixed, thumb if os.path.exists(thumb) else None

# ================= SPLIT =================

def split_file(path):
    parts = []
    with open(path, "rb") as f:
        i = 1
        while True:
            chunk = f.read(SPLIT_SIZE)
            if not chunk:
                break
            p = f"{path}.part{i}.mp4"
            with open(p, "wb") as o:
                o.write(chunk)
            parts.append(p)
            i += 1
    os.remove(path)
    return parts

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = extract_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Downloading...")

    cleanup()

    try:
        if GOFILE_RE.search(url):
            await download_gofile(GOFILE_RE.search(url).group(1), status)
        else:
            await download_ytdlp(url, status)
    except Exception as e:
        await status.edit(f"❌ Download failed\n{e}")
        cleanup()
        return

    await status.edit("🎞 Processing...")

    for f in os.listdir(DOWNLOAD_DIR):
        p = os.path.join(DOWNLOAD_DIR, f)
        if not p.lower().endswith(ALLOWED_EXT):
            continue

        fixed, thumb = fix_video(p)
        files = [fixed]

        if os.path.getsize(fixed) > SPLIT_SIZE:
            files = split_file(fixed)

        for part in files:
            await app.send_video(
                CHANNEL_ID,
                part,
                thumb=thumb,
                supports_streaming=True,
                progress=upload_progress,
                progress_args=(status,)
            )
            os.remove(part)

        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    await status.edit("✅ Uploaded to channel")
    cleanup()

# ================= START =================

app.run()
