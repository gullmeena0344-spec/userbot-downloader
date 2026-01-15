import os, re, math, shutil, subprocess, requests, time, base64
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= PROGRESS =================

_progress_cache = {}

def bar(cur, total):
    pct = (cur / total) * 100 if total else 0
    filled = int(pct / 10)
    return f"[{'█'*filled}{'░'*(10-filled)}] {pct:.1f}%"

async def progress_func(current, total, status, tag):
    now = time.time()
    key = f"{id(status)}-{tag}"

    last = _progress_cache.get(key, 0)
    if now - last < 2:
        return
    _progress_cache[key] = now

    speed = current / max((now - status.date), 1)
    eta = (total - current) / speed if speed > 0 else 0

    try:
        await status.edit(
            f"**{tag}**\n"
            f"{bar(current, total)}\n"
            f"`{current/1024/1024:.2f} / {total/1024/1024:.2f} MB`\n"
            f"🚀 `{speed/1024/1024:.2f} MB/s` | ⏳ `{int(eta)}s`"
        )
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

def extract_clean_url(text):
    m = re.search(r'(https?://[^\s]+)', text)
    return m.group(1) if m else None

# ================= GOFILE =================

async def download_gofile(content_id, status):
    headers = {
        "Authorization": f"Bearer {GOFILE_API_TOKEN}",
        "User-Agent": UA
    }

    r = requests.get(
        f"https://api.gofile.io/getContent?contentId={content_id}",
        headers=headers
    ).json()

    for item in r["data"]["children"].values():
        if item["type"] != "file":
            continue

        out = os.path.join(DOWNLOAD_DIR, item["name"])
        with requests.get(item["directLink"], stream=True) as s:
            total = int(s.headers.get("content-length", 0))
            cur = 0
            with open(out, "wb") as f:
                for chunk in s.iter_content(1024 * 1024):
                    f.write(chunk)
                    cur += len(chunk)
                    await progress_func(cur, total, status, "Downloading")

# ================= YT-DLP =================

def download_ytdlp(url, out, status):
    parsed = urlparse(url)

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", UA,
        "--add-header", f"Referer:{parsed.scheme}://{parsed.netloc}/",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    for line in proc.stdout:
        if "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                cur = pct
                await status.edit(f"**Downloading**\n[{int(pct)//10*'█'}{'░'*(10-int(pct)//10)}] {pct:.1f}%")
            except:
                pass

    proc.wait()

# ================= VIDEO FIX + THUMB =================

def faststart_and_thumb(src):
    base = src.rsplit(".", 1)[0]
    fixed = f"{base}_fixed.mp4"
    thumb = f"{base}.jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # ✅ THUMB AT 40 SECONDS
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
    url = extract_clean_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Starting download...")

    if GOFILE_RE.search(url):
        await download_gofile(GOFILE_RE.search(url).group(1), status)
    else:
        await download_ytdlp(url, os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"), status)

    await status.edit("🎞 Processing video...")

    for f in os.listdir(DOWNLOAD_DIR):
        p = os.path.join(DOWNLOAD_DIR, f)
        if not p.lower().endswith(ALLOWED_EXT):
            continue

        fixed, thumb = faststart_and_thumb(p)
        parts = [fixed]

        if os.path.getsize(fixed) > SPLIT_SIZE:
            parts = split_file(fixed)

        for part in parts:
            await client.send_video(
                m.chat.id,
                part,
                thumb=thumb,
                supports_streaming=True,
                progress=progress_func,
                progress_args=(status, "Uploading")
            )
            os.remove(part)

        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= START =================

app.run()
