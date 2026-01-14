import os
import re
import requests
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

app = Client(
    name="userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)


def download_file(url, filename):
    r = requests.get(url, stream=True)
    r.raise_for_status()
    with open(filename, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)


@app.on_message(filters.private & filters.text)
async def handler(client: Client, message: Message):
    text = message.text.strip()

    px = PIXELDRAIN_RE.search(text)
    gf = GOFILE_RE.search(text)

    if not px and not gf:
        return

    status = await message.reply("📥 Downloading...")

    try:
        if px:
            file_id = px.group(1)
            info = requests.get(f"https://pixeldrain.com/api/file/{file_id}/info").json()
            filename = info["name"]
            url = f"https://pixeldrain.com/api/file/{file_id}"

        else:
            content_id = gf.group(1)
            data = requests.get(
                f"https://api.gofile.io/getContent?contentId={content_id}"
            ).json()
            file_data = next(iter(data["data"]["contents"].values()))
            filename = file_data["name"]
            url = file_data["link"]

        filepath = os.path.join(DOWNLOAD_DIR, filename)

        download_file(url, filepath)

        await status.edit("📤 Uploading...")
        await message.reply_document(filepath)

        os.remove(filepath)

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")


app.run()
