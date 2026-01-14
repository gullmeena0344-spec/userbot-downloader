FROM python:3.10-slim

# ---------------- System dependencies ----------------
RUN apt-get update && \
    apt-get install -y \
        ffmpeg \
        aria2 \
        ca-certificates \
        wget \
        megatools \
    && rm -rf /var/lib/apt/lists/*

# ---------------- Install mega-cmd (official) ----------------
RUN wget https://mega.nz/linux/repo/Debian_11/amd64/megacmd_1.6.3-1_amd64.deb && \
    apt-get update && \
    apt-get install -y ./megacmd_1.6.3-1_amd64.deb && \
    rm megacmd_1.6.3-1_amd64.deb && \
    rm -rf /var/lib/apt/lists/*

# ---------------- App setup ----------------
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
