import os
import re
import math
import shutil
import subprocess
import requests
from pyrogram import Client, filters
from pyrogram.types import Message

# ============== CONFIG ==============

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ============== HELPERS ==============

def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

def download_ytdlp(url, out_path):
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", out_path,
        url
    ]
    subprocess.run(cmd, check=True)

def convert_mp4(src):
    dst = src.rsplit(".", 1)[0] + ".mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dst

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

# ============== BOT ==============

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Processing link...")

    try:
        files = []

        # PIXELDRAIN
        px = PIXELDRAIN_RE.search(url)
        if px:
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()

            path = os.path.join(DOWNLOAD_DIR, info["name"])
            await status.edit("⬇️ Downloading from Pixeldrain")
            download_pixeldrain(fid, path)
            files.append(path)

        # ANY OTHER URL (mp4 / m3u8 / streaming)
        else:
            await status.edit("🎥 Extracting video via yt-dlp")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)

            for f in os.listdir(DOWNLOAD_DIR):
                files.append(os.path.join(DOWNLOAD_DIR, f))

        # PROCESS FILES
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
