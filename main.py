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

ALLOWED_VIDEO_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")
ALLOWED_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= REGEX =================

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
IMGHEST_RE = re.compile(r"https?://(www\.)?imgchest\.com/p/([a-zA-Z0-9]+)")
IMGBB_RE = re.compile(r"https?://(i\.)?imgbb\.com/([a-zA-Z0-9]+)")
IMGUR_RE = re.compile(r"https?://(i\.)?imgur\.com/(a/|gallery/)?([a-zA-Z0-9]+)")
JPG6_RE = re.compile(r"https?://(www\.)?jpg6\.com/([a-zA-Z0-9]+)")
BUNKR_RE = re.compile(r"https?://(www\.)?bunkr\.")

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

def collect_files(root, exts):
    out = []
    for b, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(b, f)
            if p.lower().endswith(exts):
                out.append(p)
    return out

def download_file(url, path):
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for c in r.iter_content(1024 * 1024):
                if c:
                    f.write(c)

# ================= IMAGE HOSTS =================

def download_imgchest(pid):
    api = f"https://api.imgchest.com/v1/post/{pid}"
    data = requests.get(api).json()
    imgs = data["data"]["images"]
    paths = []
    for i in imgs:
        url = i["link"]
        name = url.split("/")[-1].split("?")[0]
        p = os.path.join(DOWNLOAD_DIR, name)
        download_file(url, p)
        paths.append(p)
    return paths

def download_imgbb(url):
    html = requests.get(url).text
    links = re.findall(r'https://i\.ibb\.co/[^"]+', html)
    paths = []
    for u in set(links):
        name = u.split("/")[-1]
        p = os.path.join(DOWNLOAD_DIR, name)
        download_file(u, p)
        paths.append(p)
    return paths

def download_imgur(url):
    if "/a/" in url or "/gallery/" in url:
        api = f"https://imgur.com/ajaxalbums/getimages/{url.split('/')[-1]}"
        data = requests.get(api).json()["data"]["images"]
        urls = [f"https://i.imgur.com/{i['hash']}{i['ext']}" for i in data]
    else:
        urls = [url if url.endswith(ALLOWED_IMAGE_EXT) else url + ".jpg"]

    paths = []
    for u in urls:
        name = u.split("/")[-1]
        p = os.path.join(DOWNLOAD_DIR, name)
        download_file(u, p)
        paths.append(p)
    return paths

def download_jpg6(pid):
    html = requests.get(f"https://jpg6.com/{pid}").text
    urls = re.findall(r'https://[^"]+\.jpg', html)
    paths = []
    for u in set(urls):
        name = u.split("/")[-1]
        p = os.path.join(DOWNLOAD_DIR, name)
        download_file(u, p)
        paths.append(p)
    return paths

# ================= MEGA =================

def download_mega(url):
    env = os.environ.copy()
    env["HOME"] = "/root"

    subprocess.run(
        ["mega-cmd-server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        check=False
    )

    subprocess.run(
        ["mega-get", "--ignore-quota-warn", "--recursive", url, DOWNLOAD_DIR],
        env=env,
        check=True
    )

# ================= VIDEO =================

def download_ytdlp(url, out):
    parsed = urlparse(url)
    ref = f"{parsed.scheme}://{parsed.netloc}/"
    subprocess.run(
        [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--user-agent", "Mozilla/5.0",
            "--referer", ref,
            "--merge-output-format", "mp4",
            "-o", out,
            url,
        ],
        check=True
    )

def faststart_and_thumb(src):
    fixed = src.replace(".mp4", "_fixed.mp4")
    thumb = src.replace(".mp4", ".jpg")

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    os.remove(src)
    return fixed, thumb

def split_file(p):
    parts = []
    with open(p, "rb") as f:
        i = 1
        while True:
            data = f.read(SPLIT_SIZE)
            if not data:
                break
            part = f"{p}.part{i}.mp4"
            with open(part, "wb") as o:
                o.write(data)
            parts.append(part)
            i += 1
    os.remove(p)
    return parts

# ================= BOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    s = await m.reply("🔍 Processing...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # BLOCKED
        if BUNKR_RE.search(url):
            await s.edit("❌ Bunkr blocked")
            return

        # IMAGES
        if (x := IMGCHEST_RE.search(url)):
            files = download_imgchest(x.group(2))
        elif IMGBB_RE.search(url):
            files = download_imgbb(url)
        elif IMGUR_RE.search(url):
            files = download_imgur(url)
        elif (x := JPG6_RE.search(url)):
            files = download_jpg6(x.group(2))

        # MEGA
        elif MEGA_RE.search(url):
            await s.edit("⬇️ MEGA download...")
            download_mega(url)
            files = collect_files(DOWNLOAD_DIR, ALLOWED_VIDEO_EXT)

        # VIDEO
        else:
            await s.edit("🎥 Video download...")
            out = os.path.join(DOWNLOAD_DIR, "%(title).80s.%(ext)s")
            download_ytdlp(url, out)
            files = collect_files(DOWNLOAD_DIR, ALLOWED_VIDEO_EXT)

        if not files:
            raise Exception("No files found")

        for f in files:
            if f.lower().endswith(ALLOWED_IMAGE_EXT):
                await app.send_photo("me", photo=f)
                os.remove(f)
            else:
                fixed, thumb = faststart_and_thumb(f)
                parts = [fixed] if os.path.getsize(fixed) < SPLIT_SIZE else split_file(fixed)
                for p in parts:
                    await app.send_video("me", video=p, thumb=thumb, supports_streaming=True)
                    os.remove(p)
                if os.path.exists(thumb):
                    os.remove(thumb)

        await s.edit("✅ Done")

    except Exception as e:
        await s.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
