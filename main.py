import os
import re
import time
import math
import shutil
import requests
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB safe split

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ================= HELPERS =================

def human(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}TB"


def download_with_progress(url, path, msg):
    r = requests.get(url, stream=True)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    done = 0
    last = time.time()

    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)

                if time.time() - last > 2:
                    percent = (done / total) * 100 if total else 0
                    msg.edit_text(
                        f"📥 Downloading\n{percent:.1f}% | {human(done)}/{human(total)}"
                    )
                    last = time.time()


def convert_to_mp4(src):
    dst = src.rsplit(".", 1)[0] + ".mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dst


def get_video_info(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    w, h, d = p.stdout.strip().split("\n")
    return int(float(w)), int(float(h)), int(float(d))


def extract_thumbnail(video_path):
    thumb = video_path.rsplit(".", 1)[0] + ".jpg"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", "00:00:01",
            "-vframes", "1",
            thumb
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return thumb


def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)

    with open(path, "rb") as f:
        for i in range(count):
            part_path = f"{path}.part{i+1}"
            with open(part_path, "wb") as p:
                p.write(f.read(SPLIT_SIZE))
            parts.append(part_path)

    os.remove(path)
    return parts

# ================= BOT =================

@app.on_message(filters.private & filters.text)
async def handler(client: Client, message: Message):
    text = message.text.strip()

    px = PIXELDRAIN_RE.search(text)
    gf = GOFILE_RE.search(text)

    if not px and not gf:
        return

    status = await message.reply("🔍 Fetching info...")

    try:
        files = []

        if px:
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()
            files.append({
                "name": info["name"],
                "url": f"https://pixeldrain.com/api/file/{fid}",
            })

        else:
            cid = gf.group(1)
            data = requests.get(
                f"https://api.gofile.io/getContent?contentId={cid}"
            ).json()
            for f in data["data"]["contents"].values():
                if f["type"] == "file":
                    files.append({
                        "name": f["name"],
                        "url": f["link"],
                    })

        for item in files:
            filename = item["name"]
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            await status.edit(f"📥 Downloading\n{filename}")
            download_with_progress(item["url"], filepath, status)

            if not filepath.lower().endswith(".mp4"):
                await status.edit("🎬 Converting to MP4")
                new_path = convert_to_mp4(filepath)
                os.remove(filepath)
                filepath = new_path

            size = os.path.getsize(filepath)

            if size > SPLIT_SIZE:
                await status.edit("✂️ Splitting large file")
                parts = split_file(filepath)
            else:
                parts = [filepath]

            for idx, part in enumerate(parts, start=1):
                await status.edit(f"📤 Uploading part {idx}/{len(parts)}")

                width, height, duration = get_video_info(part)
                thumb = extract_thumbnail(part)

                await message.reply_video(
                    video=part,
                    thumb=thumb,
                    width=width,
                    height=height,
                    duration=duration,
                    supports_streaming=True,
                    caption=os.path.basename(part),
                    progress=lambda c, t: status.edit_text(
                        f"📤 Uploading\n{(c/t)*100:.1f}%"
                    ),
                )

                os.remove(thumb)
                os.remove(part)

        await status.edit("✅ Done & cleaned")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
