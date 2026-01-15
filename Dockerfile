FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

# ---------- system deps ----------
RUN apt-get update && apt-get install -y \
    ffmpeg \
    aria2 \
    wget \
    curl \
    ca-certificates \
    gnupg \
    default-jre-headless \
    unzip \
    megatools \
    && rm -rf /var/lib/apt/lists/*

# ---------- JDOWNLOADER HEADLESS ----------
RUN mkdir -p /opt/jdownloader && \
    wget -O /opt/jdownloader/JDownloader.jar https://installer.jdownloader.org/JDownloader.jar

# Wrapper command
RUN echo '#!/bin/bash\njava -jar /opt/jdownloader/JDownloader.jar -norestart &' > /usr/local/bin/jdownloader \
    && chmod +x /usr/local/bin/jdownloader

# ---------- APP SETUP ----------
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Start aria2 daemon and JDownloader in background before running the bot
CMD aria2c --enable-rpc --rpc-listen-all --rpc-allow-origin-all --daemon && \
    jdownloader && \
    python main.py
