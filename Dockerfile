FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Create non-root user (UID 1000 is standard for Hugging Face Spaces & cloud PaaS)
RUN useradd -m -u 1000 scholar

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

COPY --chown=scholar:scholar . /app

# Prepare default app data folder with proper ownership
RUN mkdir -p /app/data/uploads /app/data/tts_cache && \
    chown -R scholar:scholar /app/data

USER scholar

# Hugging Face Spaces uses 7860 by default; Render/Railway inject $PORT automatically
ENV PORT=7860
EXPOSE 7860

CMD ["sh", "-c", "if [ -d /data ] && [ -w /data ]; then export SCHOLAR_DATA_DIR=/data; fi; exec uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
