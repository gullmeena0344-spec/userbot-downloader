import os, re, math, shutil, subprocess, requests, time, aria2p
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = "GOFILE_API_TOKEN_MASKED" 

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024 
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= ARIA2 SETUP =================
# Start aria2 daemon in background
subprocess.Popen(["aria2c", "--enable-rpc", "--rpc-listen-all", "--rpc-allow-origin-all", "--max-connection-per-server=16", "--split=16", "--min-split-size=1M", "--daemon"])
time.sleep(2)
aria2 = aria2p.API(aria2p.Client(host="http://localhost", port=6800, secret=""))

# ================= PROGRESS HELPER =================
async def aria2_progress(gid, message, tag):
    while True:
        try:
            download = aria2.get_download(gid)
            if download.is_complete: break
            if download.has_failed: raise Exception("Aria2 download failed.")
            
            bar = f"[{'█' * int(download.progress / 10)}{'░' * (10 - int(download.progress / 10))}] {download.progress:.1f}%"
            msg = f"**{tag}**\n{bar}\n`{download.completed_length_string()} / {download.total_length_string()}`\n🚀 Speed: `{download.download_speed_string()}`"
            await message.edit(msg)
            time.sleep(4)
        except: break

# ================= CLIENT =================
app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# ---------- GOFILE ARIA2 LEECH ----------
async def download_gofile_aria(content_id, status_msg):
    headers = {"Authorization": f"Bearer {GOFILE_API_TOKEN}", "User-Agent": UA}
    api_url = f"api.gofile.io{content_id}"
    
    res = requests.get(api_url, headers=headers)
    data = res.json()
    contents = data.get("data", {}).get("contents", {})
    
    video_items = [item for item in contents.values() if item.get("type") == "file"]
    
    for i, item in enumerate(video_items, 1):
        tag = f"Leeching Video {i}/{len(video_items)}"
        options = {"dir": DOWNLOAD_DIR, "out": item["name"], "header": f"Authorization: Bearer {GOFILE_API_TOKEN}"}
        
        # Add to Aria2 (Multi-threaded download)
        download = aria2.add_uris([item["directLink"]], options=options)
        await aria2_progress(download.gid, status_msg, tag)

# ---------- HANDLER ----------
@app.on_message(filters.me & filters.private & filters.text)
async def handler(client, m: Message):
    if m.chat.id != client.me.id: return
    
    url = re.search(r'(https?://[^\s\n]+)', m.text)
    if not url: return
    url = url.group(1)
    
    status = await m.reply("🚀 Multi-Threaded Leech Active...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if (gf := GOFILE_RE.search(url)):
            await download_gofile_aria(gf.group(1), status)
        else:
            # Fallback to standard yt-dlp for other links
            cmd = ["yt-dlp", "--no-playlist", "-o", f"{DOWNLOAD_DIR}/%(title)s.%(ext)s", url]
            subprocess.run(cmd, check=True)

        for f in os.listdir(DOWNLOAD_DIR):
            f_path = os.path.join(DOWNLOAD_DIR, f)
            await client.send_video("me", video=f_path, caption=f"`{f}`")
            os.remove(f_path)

        await status.edit("✅ Done.")
    except Exception as e:
        await status.edit(f"❌ Error: `{e}`")

if __name__ == "__main__":
    app.run()
