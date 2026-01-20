import subprocess
from pathlib import Path

class Downloader:
    def __init__(self, out_dir="downloads"):
        self.out = Path(out_dir)
        self.out.mkdir(exist_ok=True)

    def download(self, url):
        """
        Download video using yt-dlp and return Path to downloaded file.
        """
        out_template = str(self.out / "%(title).200s.%(ext)s")
        cmd = [
            "yt-dlp",
            "-f", "bv*+ba/b",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", out_template,
            url
        ]
        subprocess.run(cmd, check=True)
        files = sorted(self.out.glob("*"), key=lambda x: x.stat().st_mtime)
        return files[-1] if files else None


def generate_thumb(video_path: Path):
    """
    Generate thumbnail from 3-second mark.
    """
    thumb_path = video_path.with_suffix(".jpg")
    subprocess.run([
        "ffmpeg", "-ss", "00:00:03",
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(thumb_path)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return str(thumb_path) if thumb_path.exists() else None


def split_file(file_path: Path, chunk_size=1990 * 1024 * 1024):
    """
    Split file into chunks for Telegram (>2GB safe).
    Returns list of Path objects.
    """
    parts = []
    file_size = file_path.stat().st_size
    if file_size <= chunk_size:
        return [file_path]

    with open(file_path, "rb") as f:
        part_num = 1
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            part_path = file_path.with_name(f"{file_path.stem}_part{part_num}.mp4")
            with open(part_path, "wb") as pf:
                pf.write(data)
            parts.append(part_path)
            part_num += 1
    return parts
