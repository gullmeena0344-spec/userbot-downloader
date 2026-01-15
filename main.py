import os, re, math, shutil, subprocess, requests, time
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN")

DOWNLOAD_DIR = "downloads"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

GOFILE_RE = re.compile(r"gofile\.io/d/([A-Za-z0-9]+)")

# ================= HELPERS =================

async def progress_bar(current, total, message, tag):
    now = time.time()
    if not hasattr(progress_bar, "last"): progress_bar.last = 0
    if now - progress_bar.last < 4: return 
    progress_bar.last = now
    
    percentage = (current / total) * 100 if total > 0 else 0
    bar = f"[{'█' * int(percentage/10)}{'░' * (10 - int(percentage/10))}] {percentage:.1f}%"
    try:
        await message.edit(f"**{tag}**\n{bar}\n`{current/1024/1024:.1f} / {total/1024/1024:.1f} MB`")
    except: pass

async def download_file(url, path, message, tag):
    headers = {"User-Agent": UA, "Authorization": f"Bearer {GOFILE_API_TOKEN}"}
    with requests.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        current = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
                current += len(chunk)
                await progress_bar(current, total, message, tag)

def fix_video(src):
    """Fixes the video and ensures the file exists before returning the path."""
    fixed = src.replace(".mp4", "_fixed.mp4")
    # Using ffmpeg to fix headers for streaming
    process = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        capture_output=True, text=True
    )
    if os.path.exists(src): os.remove(src)
    
    if not os.path.exists(fixed):
        raise Exception(f"FFmpeg failed to create fixed video: {process.stderr}")
    return fixed

# ================= BOT HANDLER =================

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

@app.on_message(filters.private & filters.text)
async def handler(client, m: Message):
    match = re.search(r'(https?://[^\s]+)', m.text)
    if not match: return
    url = match.group(1)
    status = await m.reply("📂 **Analyzing Link...**")

    try:
        queue = []
        if (gf := GOFILE_RE.search(url)):
            content_id = gf.group(1)
            # FIXED URL CONSTRUCTION
            api_url = f"api.gofile.io{content_id}"
            
            res = requests.get(api_url, headers={"Authorization": f"Bearer {GOFILE_API_TOKEN}"})
            if res.status_code != 200:
                raise Exception(f"GoFile API Error {res.status_code}. Premium token required in 2026.")
            
            data = res.json()
            contents = data["data"].get("children", data["data"].get("contents", {}))
            queue = [{"name": item["name"], "link": item["directLink"]} for item in contents.values() if item["type"] == "file"]
        else:
            queue = [{"name": "video.mp4", "link": url}]

        for i, item in enumerate(queue, 1):
            tag = f"Video ({i}/{len(queue)})"
            file_path = os.path.join(DOWNLOAD_DIR, item["name"])
            
            await download_file(item["link"], file_path, status, f"Downloading {tag}")
            
            await status.edit(f"⚙️ **Processing {tag}...**")
            fixed_file = fix_video(file_path)
            
            await status.edit(f"⬆️ **Uploading {tag}...**")
            # PASSING THE ABSOLUTE PATH TO PREVENT DECODE ERRORS
            abs_path = os.path.abspath(fixed_file)
            
            await client.send_video(
                chat_id=m.chat.id,
                video=abs_path,
                caption=f"✅ {tag}\n`{item['name']}`",
                supports_streaming=True,
                progress=progress_bar,
                progress_args=(status, f"Uploading {tag}")
            )
            
            if os.path.exists(fixed_file): os.remove(fixed_file)

        await status.edit(f"✅ **Done!** {len(queue)} videos sent.")

    except Exception as e:
        await status.edit(f"❌ **Error:**\n`{str(e)}`")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        if not os.path.exists(DOWNLOAD_DIR): os.makedirs(DOWNLOAD_DIR)

if __name__ == "__main__":
    app.run()
