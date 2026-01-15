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
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN") # Add this to your Env Vars

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
BUNKR_RE = re.compile(r"https?://(?:[a-z0-9]+\.)?bunkr\.(?:cr|pk|fi|ru|black|st)/")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= COOKIES =================

def ensure_cookies():
    if os.path.exists(COOKIES_FILE):
        return
    data = os.getenv("COOKIES_B64")
    if data:
        with open(COOKIES_FILE, "wb") as f:
            f.write(base64.b64decode(data))
    else:
        # Create empty file to prevent yt-dlp error if var missing
        open(COOKIES_FILE, 'a').close()

ensure_cookies()

# ================= HELPERS =================

def collect_files(root):
    files = []
    for base, _, names in os.walk(root):
        for n in names:
            p = os.path.join(base, n)
            # Match any file since yt-dlp might name it differently
            if any(p.lower().endswith(ext) for ext in ALLOWED_EXT):
                files.append(p)
    return files

# ---------- GOFILE (2026 Updated) ----------
def download_gofile(content_id):
    if not GOFILE_API_TOKEN:
        raise Exception("GOFILE_API_TOKEN missing in environment variables")
    
    headers = {
        "Authorization": f"Bearer {GOFILE_API_TOKEN}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # Get content info
    res = requests.get(f"api.gofile.io{content_id}", headers=headers)
    if res.status_code != 200:
        raise Exception(f"GoFile API Error {res.status_code}. Ensure token is Premium.")
    
    data = res.json()
    contents = data["data"].get("children", data["data"].get("contents", {}))
    
    downloaded_paths = []
    for item_id in contents:
        item = contents[item_id]
        if item["type"] == "file":
            file_path = os.path.join(DOWNLOAD_DIR, item["name"])
            # Download direct link
            with requests.get(item["directLink"], headers=headers, stream=True) as r:
                r.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            downloaded_paths.append(file_path)
    return downloaded_paths

# ---------- PIXELDRAIN ----------
def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            f.write(c)

# ---------- YT-DLP (Fixed Recursion & Headers) ----------
def download_ytdlp(url, out_pattern):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "--add-header", f"Referer:{referer}",
        "--merge-output-format", "mp4",
        "-o", out_pattern,
        url # url is strictly the extracted string
    ]
    subprocess.run(cmd, check=True)

# ---------- VIDEO FIXING ----------
def faststart_and_thumb(src):
    base = src.rsplit(".", 1)[0]
    fixed = f"{base}_fixed.mp4"
    thumb = f"{base}.jpg"

    # Faststart
    subprocess.run(["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Thumbnail
    subprocess.run(["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:01", "-vframes", "1", thumb], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if os.path.exists(src): os.remove(src)
    return fixed, (thumb if os.path.exists(thumb) else None)

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

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    # Extract only the URL from potential message text
    url_match = re.search(r'(https?://[^\s]+)', m.text)
    if not url_match:
        return
    
    url = url_match.group(1)
    status = await m.reply("🔍 Processing link...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if BUNKR_RE.search(url):
            # Bunkr requires specific Referer headers usually handled by yt-dlp
            await status.edit("⬇️ Attempting Bunkr Download...")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)

        elif (px := PIXELDRAIN_RE.search(url)):
            fid = px.group(1)
            info = requests.get(f"https://pixeldrain.com/api/file/{fid}/info").json()
            path = os.path.join(DOWNLOAD_DIR, info["name"])
            await status.edit("⬇️ Downloading Pixeldrain...")
            download_pixeldrain(fid, path)

        elif (gf := GOFILE_RE.search(url)):
            await status.edit("⬇️ Downloading GoFile Folder...")
            download_gofile(gf.group(1))

        elif MEGA_RE.search(url):
            await status.edit("⬇️ Downloading MEGA...")
            subprocess.run(["megadl", "--path", DOWNLOAD_DIR, url], check=True)

        else:
            await status.edit("🎥 Extracting with YT-DLP...")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)

        files = collect_files(DOWNLOAD_DIR)
        if not files:
            raise Exception("No supported files found after download.")

        await status.edit(f"📦 Found {len(files)} files. Uploading...")

        for f in files:
            fixed, thumb = faststart_and_thumb(f)
            parts = [fixed] if os.path.getsize(fixed) < SPLIT_SIZE else split_file(fixed)

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    thumb=thumb,
                    supports_streaming=True,
                    caption=f"`{os.path.basename(p)}`"
                )
                if os.path.exists(p): os.remove(p)
            if thumb and os.path.exists(thumb): os.remove(thumb)

        await status.edit("✅ All files processed and sent to 'Saved Messages'")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{str(e)}`")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

if __name__ == "__main__":
    app.run()
