import os, re, math, shutil, subprocess, requests, time, asyncio, aria2p
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN") 

DOWNLOAD_DIR = "downloads"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= ARIA2 SETUP =================
subprocess.Popen(["aria2c", "--enable-rpc", "--rpc-listen-all", "--rpc-allow-origin-all", "--max-connection-per-server=16", "--split=16", "--daemon"])
time.sleep(2)
aria2 = aria2p.API(aria2p.Client(host="http://localhost", port=6800, secret=""))

# ================= HELPERS =================
def get_progress_bar(current, total):
    percentage = (current / total) * 100 if total > 0 else 0
    done = int(percentage / 10)
    return f"[{'█' * done}{'░' * (10 - done)}] {percentage:.1f}%"

async def tg_progress(current, total, message, tag):
    now = time.time()
    if not hasattr(tg_progress, "last"): tg_progress.last = 0
    if now - tg_progress.last < 4: return 
    tg_progress.last = now
    bar = get_progress_bar(current, total)
    try:
        await message.edit(f"**{tag}**\n{bar}\n`{current/1024/1024:.2f} / {total/1024/1024:.2f} MB`")
    except: pass

async def aria2_progress(gid, message, tag):
    while True:
        try:
            download = aria2.get_download(gid)
            if download.is_complete: break
            if download.has_failed: raise Exception("Aria2 download failed.")
            bar = get_progress_bar(download.completed_length, download.total_length)
            msg = (f"**{tag}**\n{bar}\n`{download.completed_length_string()} / {download.total_length_string()}`\n🚀 Speed: `{download.download_speed_string()}`")
            await message.edit(msg)
            await asyncio.sleep(4)
        except: break

def generate_thumbnail(video_path):
    thumb_path = f"{video_path}.jpg"
    # Captures a frame at 1 second. FFmpeg must be in Dockerfile.
    cmd = ["ffmpeg", "-y", "-i", video_path, "-ss", "00:00:01", "-vframes", "1", thumb_path]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return thumb_path if os.path.exists(thumb_path) else None

# ================= CLIENT =================
app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

async def download_gofile_aria(content_id, status_msg):
    headers = {"Authorization": f"Bearer {GOFILE_API_TOKEN}", "User-Agent": UA}
    api_url = f"api.gofile.io{content_id}"
    res = requests.get(api_url, headers=headers)
    if res.status_code != 200:
        raise Exception(f"GoFile API Error {res.status_code}. Verify Token.")
    
    data = res.json()
    contents = data.get("data", {}).get("contents", data.get("data", {}).get("children", {}))
    video_items = [item for item in contents.values() if item.get("type") == "file"]
    
    for i, item in enumerate(video_items, 1):
        tag = f"Leeching {i}/{len(video_items)}"
        options = {"dir": DOWNLOAD_DIR, "out": item["name"], "header": f"Authorization: Bearer {GOFILE_API_TOKEN}"}
        download = aria2.add_uris([item["directLink"]], options=options)
        await aria2_progress(download.gid, status_msg, tag)

# ================= HANDLER =================
@app.on_message(filters.me & filters.private & filters.text)
async def handler(client, m: Message):
    if m.chat.id != client.me.id: return 
    url_match = re.search(r'(https?://[^\s\n]+)', m.text)
    if not url_match: return
    url = url_match.group(1)
    
    status = await m.reply("🛰️ Initializing Download...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if (gf := GOFILE_RE.search(url)):
            await status.edit("📁 GoFile detected. Multi-thread leeching...")
            await download_gofile_aria(gf.group(1), status)
        else:
            download = aria2.add_uris([url], options={"dir": DOWNLOAD_DIR})
            await aria2_progress(download.gid, status, "Downloading Link")

        files = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR) if not f.endswith('.jpg')]
        for i, f_path in enumerate(files, 1):
            tag = f"Uploading {i}/{len(files)}"
            thumb = generate_thumbnail(f_path)
            
            await client.send_video(
                chat_id="me", 
                video=f_path, 
                thumb=thumb,
                supports_streaming=True,
                caption=f"`{os.path.basename(f_path)}`",
                progress=tg_progress,
                progress_args=(status, tag)
            )
            if thumb and os.path.exists(thumb): os.remove(thumb)
            os.remove(f_path)

        await status.edit("✅ Success! Check Saved Messages.")
    except Exception as e:
        await status.edit(f"❌ Error: `{e}`")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

if __name__ == "__main__":
    app.run()
