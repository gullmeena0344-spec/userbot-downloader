import os
import asyncio
from pathlib import Path
from pyrogram import Client, filters
from pyrogram.types import Message
from downloader import Downloader, generate_thumb, split_file  # fixed import

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION_STRING")

bot = Client(session_name=SESSION, api_id=API_ID, api_hash=API_HASH)
dl = Downloader()


async def progress_bar(current, total, msg, prefix=""):
    """
    Updates Telegram message with progress.
    """
    try:
        percent = current / total * 100
        await msg.edit(f"{prefix}{percent:.1f}%")
    except:
        pass


async def upload_file(m: Message, file_path: Path, thumb=None):
    """
    Uploads file to Telegram with optional progress bar and splits >2GB.
    """
    status_msg = await m.reply("⬆️ Uploading...")
    parts = split_file(file_path)
    for part in parts:
        loop = asyncio.get_event_loop()

        def progress_callback(current, total):
            asyncio.run_coroutine_threadsafe(
                progress_bar(current, total, status_msg, prefix="⬆️ Uploading: "),
                loop
            )

        await m.reply_video(
            video=str(part),
            supports_streaming=True,
            thumb=thumb,
            progress=progress_callback
        )
    await status_msg.delete()


@bot.on_message(filters.me & filters.text)
async def grab(_, m: Message):
    """
    Handles incoming links in Saved Messages (filters.me).
    """
    url = m.text.strip()
    if not url.startswith("http"):
        return

    status_msg = await m.reply("⬇️ Starting download...")

    try:
        loop = asyncio.get_event_loop()
        # download in separate thread
        file_path = await loop.run_in_executor(None, dl.download, url)

        if not file_path:
            return await status_msg.edit("❌ Download failed")

        # generate thumbnail
        thumb = generate_thumb(file_path)

        # upload (split if needed)
        await upload_file(m, file_path, thumb)

        await status_msg.delete()

    except Exception as e:
        await status_msg.edit(f"❌ {e}")


if __name__ == "__main__":
    bot.run()
