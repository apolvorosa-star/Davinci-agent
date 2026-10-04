# DaVinci Agent - imagen CLI (transcripcion + generacion de contenido)
# La GUI (CustomTkinter) no corre en contenedor: usa python app.py en local.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg es obligatorio: whisper/pydub lo invocan para normalizar el audio.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias primero para aprovechar la cache de capas.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Datos y config viven fuera de la imagen (montar como volumenes).
VOLUME ["/app/input", "/app/output", "/app/config"]

# El entrypoint es la CLI: `docker run davinci-agent video.mp4`, `--watch`, `--list`...
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
