FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
        ffmpeg \
        aria2 \
        megatools \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App files
COPY . .

CMD ["python", "main.py"]
