FROM python:3.12-slim-bookworm

# Ambiente Python. IMAGEIO_FFMPEG_EXE aponta pro ffmpeg do sistema
# (o imageio-ffmpeg baixaria um binário glibc próprio; usar o do apt evita isso).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg

WORKDIR /app

# libcairo2: render de stickers Lottie/.tgs (lottie -> cairocffi).
# ffmpeg: conversão de stickers de vídeo (.webm) -> GIF (imageio).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libcairo2 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copia dependências e instala
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código do projeto
COPY . .

# Define a entrada do container
CMD ["python", "main.py"]
