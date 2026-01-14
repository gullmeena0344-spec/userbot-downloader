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
GOFILE_TOKEN = os.getenv("GOFILE_TOKEN")  # optional fallback

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"

ALLOWED_EXT = (
    ".mp4", ".mkv", ".webm", ".avi", ".mov"
)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")
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

def normalize_mega_url(url):
    if "/folder/" in url:
        return url.split("/folder/")[0]
    return url

# ================= DOWNLOADERS =================

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
    subprocess.run(
        ["megadl", "--recursive", "--path", DOWNLOAD_DIR, normalize_mega_url(url)],
        check=True
    )

# ---------- GOFILE (PUBLIC FIXED) ----------
def download_gofile_public(folder_id):
    r = requests.get(
        f"https://api.gofile.io/contents/{folder_id}",
        params={"wt": "4fd6sg89d7s6"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20
    )
    r.raise_for_status()
    data = r.json()

    if data.get("status") != "ok":
        raise Exception("Public GoFile blocked")

    for info in data["data"]["contents"].values():
        if info["type"] != "file":
            continue

        name = info["name"]
        if not name.lower().endswith(ALLOWED_EXT):
            continue

        path = os.path.join(DOWNLOAD_DIR, name)
        with requests.get(info["link"], stream=True) as d:
            d.raise_for_status()
            with open(path, "wb") as f:
                for chunk in d.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)

# ---------- GOFILE (TOKEN FALLBACK) ----------
def download_gofile_token(folder_id):
    if not GOFILE_TOKEN:
        raise Exception("GOFILE_TOKEN not set")

    r = requests.get(
        f"https://api.gofile.io/contents/{folder_id}",
        headers={
            "Authorization": f"Bearer {GOFILE_TOKEN}",
            "User-Agent": "Mozilla/5.0"
        },
        timeout=20
    )
    r.raise_for_status()
    data = r.json()

    if data.get("status") != "ok":
        raise Exception("Token GoFile blocked")

    for info in data["data"]["contents"].values():
        if info["type"] != "file":
            continue

        name = info["name"]
        if not name.lower().endswith(ALLOWED_EXT):
            continue

        path = os.path.join(DOWNLOAD_DIR, name)
        with requests.get(info["link"], stream=True) as d:
            d.raise_for_status()
            with open(path, "wb") as f:
                for chunk in d.iter_content(1024 * 1024):
                    if chunk:
                        f.write(chunk)

# ---------- YT-DLP (UNCHANGED) ----------
def download_ytdlp(url, out):
    p = urlparse(url)
    ref = f"{p.scheme}://{p.netloc}/"

    subprocess.run([
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0",
        "--add-header", f"Referer:{ref}",
        "--add-header", f"Origin:{ref}",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ], check=True)

# ---------- FIX STREAMING ----------
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

# ---------- SPLIT ----------
def split_file(path):
    size = os.path.getsize(path)
    parts = math.ceil(size / SPLIT_SIZE)
    out = []

    with open(path, "rb") as f:
        for i in range(parts):
            p = f"{path}.part{i+1}.mp4"
            with open(p, "wb") as o:
                o.write(f.read(SPLIT_SIZE))
            out.append(p)

    os.remove(path)
    return out

# ================= USERBOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Processing...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if BUNKR_RE.search(url):
            await status.edit("❌ Bunkr blocked on Railway")
            return

        if (px := PIXELDRAIN_RE.search(url)):
            await status.edit("⬇️ Pixeldrain...")
            info = requests.get(f"https://pixeldrain.com/api/file/{px.group(1)}/info").json()
            download_pixeldrain(px.group(1), os.path.join(DOWNLOAD_DIR, info["name"]))

        elif (gf := GOFILE_RE.search(url)):
            await status.edit("⬇️ GoFile (public)...")
            try:
                download_gofile_public(gf.group(1))
            except Exception:
                await status.edit("🔐 GoFile token fallback...")
                download_gofile_token(gf.group(1))
            # ⛔ STOP HERE – NEVER yt-dlp
        elif MEGA_RE.search(url):
            await status.edit("⬇️ MEGA...")
            download_mega(url)

        else:
            await status.edit("🎥 yt-dlp...")
            download_ytdlp(url, os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"))

        files = collect_files(DOWNLOAD_DIR)
        if not files:
            raise Exception("No videos found")

        await status.edit(f"📦 Uploading {len(files)} file(s)...")

        for f in files:
            fixed, thumb = faststart_and_thumb(f)
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

            if os.path.exists(thumb):
                os.remove(thumb)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
