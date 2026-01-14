import os
import re
import asyncio
import subprocess
import shutil
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

URL_RE = re.compile(r"https?://\S+")

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= UTILS =================

def safe_size(path, min_mb=5):
    return os.path.exists(path) and os.path.getsize(path) > min_mb * 1024 * 1024


def generate_thumb(video):
    thumb = video.rsplit(".", 1)[0] + ".jpg"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video,
            "-ss", "00:00:01",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            thumb
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return thumb if os.path.exists(thumb) else None


def process_video(src):
    base = src.rsplit(".", 1)[0]
    remuxed = base + "_remux.mp4"
    encoded = base + "_encoded.mp4"

    # ---------- TRY SAFE REMUX ----------
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-err_detect", "ignore_err",
            "-i", src,
            "-map", "0",
            "-c", "copy",
            "-movflags", "+faststart",
            remuxed
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if safe_size(remuxed):
        os.remove(src)
        return remuxed

    # ---------- TRY SAFE RE-ENCODE ----------
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-err_detect", "ignore_err",
            "-i", src,
            "-map", "0:v:0?",
            "-map", "0:a:0?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            encoded
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if safe_size(encoded):
        if os.path.exists(remuxed):
            os.remove(remuxed)
        os.remove(src)
        return encoded

    # ---------- LAST RESORT ----------
    if os.path.exists(remuxed):
        os.remove(remuxed)
    if os.path.exists(encoded):
        os.remove(encoded)

    return src  # never crash, always return something


async def yt_download(url):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-o", out,
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--newline",
        url
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await proc.communicate()

    files = sorted(
        [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)],
        key=os.path.getmtime,
        reverse=True
    )

    return files[0] if files else None

# ================= HANDLER =================

@app.on_message(filters.text)
async def handler(_, msg: Message):
    urls = URL_RE.findall(msg.text or "")
    if not urls:
        return

    url = urls[0]
    status = await msg.reply("⬇️ Downloading…")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        file = await yt_download(url)
        if not file or not os.path.exists(file):
            await status.edit("❌ Download failed")
            return

        file = process_video(file)
        thumb = generate_thumb(file)

        await status.edit("⬆️ Uploading…")

        await app.send_video(
            "me",
            video=file,
            thumb=thumb,
            supports_streaming=True,
            caption=os.path.basename(file)
        )

        await status.delete()

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= RUN =================

app.run()
