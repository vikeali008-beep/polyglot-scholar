#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
mkdir -p data/uploads data/tts_cache
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}"
