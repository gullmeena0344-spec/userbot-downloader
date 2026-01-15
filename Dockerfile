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
    && rm -rf /var/lib/apt/lists/*

# ---------- JDOWNLOADER HEADLESS ----------
RUN mkdir -p /opt/jdownloader && \
    wget -O /opt/jdownloader/JDownloader.jar https://installer.jdownloader.org/JDownloader.jar

# Wrapper command
RUN echo '#!/bin/bash\njava -jar /opt/jdownloader/JDownloader.jar -norestart' > /usr/local/bin/jdownloader \
    && chmod +x /usr/local/bin/jdownloader

# ---------- MEGA ----------
RUN apt-get update && apt-get install -y megatools && rm -rf /var/lib/apt/lists/*

RUN wget -qO - https://mega.nz/linux/repo/Debian_11/Release.key | gpg --dearmor > /usr/share/keyrings/mega.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/mega.gpg] https://mega.nz/linux/repo/Debian_11/ ./" > /etc/apt/sources.list.d/mega.list \
 && apt-get update \
 && apt-get install -y megacmd \
 && rm -rf /var/lib/apt/lists/*

# ---------- APP ----------
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
