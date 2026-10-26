import hashlib
from pathlib import Path
from typing import Optional

from .db import DATA_DIR, get_settings
from .nlp_engine import detect_lang, strip_stress

try:
    import edge_tts
except Exception:
    edge_tts = None

TTS_CACHE_DIR = DATA_DIR / "tts_cache"
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


async def synthesize_speech_mp3(text: str, lang: Optional[str] = None, slow: bool = False, owner_id: str = "default") -> bytes:
    clean = strip_stress(text).strip()
    if not clean:
        raise ValueError("朗读文本为空")
    # Cap length per request to keep TTS fast
    if len(clean) > 1200:
        clean = clean[:1200]

    detected = lang if lang in ("ru", "en") else detect_lang(clean)
    cfg = get_settings(owner_id=owner_id, mask_secret=False)
    voice = cfg.get("ru_voice", "ru-RU-SvetlanaNeural") if detected == "ru" else cfg.get("en_voice", "en-US-AriaNeural")
    rate = "-25%" if slow else "+0%"

    key = hashlib.sha256(f"{voice}|{rate}|{clean}".encode("utf-8")).hexdigest()[:24]
    cache_file = TTS_CACHE_DIR / f"{key}.mp3"
    if cache_file.exists() and cache_file.stat().st_size > 200:
        return cache_file.read_bytes()

    if edge_tts is None:
        raise RuntimeError("edge-tts 未安装")

    comm = edge_tts.Communicate(clean, voice=voice, rate=rate)
    audio_chunks = bytearray()
    async for chunk in comm.stream():
        if chunk.get("type") == "audio":
            audio_chunks.extend(chunk["data"])

    data = bytes(audio_chunks)
    if len(data) > 200:
        cache_file.write_bytes(data)
    return data
