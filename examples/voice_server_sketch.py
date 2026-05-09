"""Sketch: Voice app server migrated to agentkit VoiceService.

Shows how server.py would look with BusParticipant handling bus comms.
The VoiceService replaces wait_for_reply_blocking with async wait_for_reply.
"""

from __future__ import annotations

import asyncio
import io
import json
import tempfile
import numpy as np
import soundfile as sf
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agentkit.bus.voice import VoiceService
from agentkit.bus.config import BusConfig

# ── FastAPI app (same as before, minus bus logic) ──

app = FastAPI()
STATIC_DIR = Path(__file__).parent / "static"

# TTS/STT models loaded on startup (unchanged)
pipelines = {}
whisper_model = None
DEFAULT_VOICES = {"en": "af_heart", "ja": "jf_alpha"}

# VoiceService instance — set after creation
voice_service: VoiceService | None = None


@app.on_event("startup")
def load_models():
    global whisper_model
    from kokoro import KPipeline
    from faster_whisper import WhisperModel
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    pipelines["en"] = KPipeline(lang_code="a", device=device)
    pipelines["ja"] = KPipeline(lang_code="j", device=device)
    whisper_model = WhisperModel("medium", device=device, compute_type="float16" if device == "cuda" else "int8")


class TTSRequest(BaseModel):
    text: str
    lang: str = "en"
    voice: str = ""


@app.post("/tts")
async def tts(req: TTSRequest):
    lang = "ja" if req.lang.startswith("ja") else "en"
    pipeline = pipelines.get(lang, pipelines["en"])
    voice = req.voice or DEFAULT_VOICES.get(lang, "af_heart")
    samples = []
    for _, _, audio in pipeline(req.text, voice=voice):
        samples.append(audio)
    if not samples:
        return {"error": "no audio generated"}
    audio = np.concatenate(samples)
    buf = io.BytesIO()
    sf.write(buf, audio, 24000, format="WAV")
    buf.seek(0)
    return StreamingResponse(buf, media_type="audio/wav")


@app.post("/stt")
async def stt(file: UploadFile = File(...), language: str = Form(default="")):
    audio_bytes = await file.read()
    tmp = io.BytesIO(audio_bytes)
    segments, info = whisper_model.transcribe(tmp, language=language or None, beam_size=5, vad_filter=True)
    text = " ".join(seg.text.strip() for seg in segments)
    return {"text": text, "language": info.language, "duration": round(info.duration, 2)}


@app.websocket("/voice/ws")
async def voice_ws(websocket: WebSocket):
    agent = websocket.query_params.get("agent", "kiro")
    await websocket.accept()
    await websocket.send_json({"type": "status", "text": f"Connected to {agent}"})

    try:
        while True:
            audio_bytes = await websocket.receive_bytes()
            if len(audio_bytes) < 5000:
                await websocket.send_json({"type": "status", "text": "Recording too short."})
                await websocket.send_json({"type": "done"})
                continue

            # STT
            await websocket.send_json({"type": "status", "text": "Transcribing..."})
            text, lang = await asyncio.to_thread(_transcribe, audio_bytes)
            if not text.strip():
                await websocket.send_json({"type": "status", "text": "Couldn't hear anything."})
                await websocket.send_json({"type": "done"})
                continue

            await websocket.send_json({"type": "transcript", "text": text, "lang": lang})

            # Send to agent via agentkit (no more raw ZMQ!)
            await websocket.send_json({"type": "status", "text": f"Asking {agent}..."})
            request_id = f"{agent}-{id(websocket)}"
            await voice_service.send_to_agent(agent, text)

            # Wait for reply via BusParticipant message loop
            response_text = None
            try:
                response_text = await asyncio.wait_for(
                    voice_service.wait_for_reply(request_id, timeout=180),
                    timeout=180,
                )
            except asyncio.TimeoutError:
                pass

            if not response_text:
                await websocket.send_json({"type": "response", "text": "(no response)"})
                await websocket.send_json({"type": "done"})
                continue

            await websocket.send_json({"type": "response", "text": response_text})

            # TTS
            await websocket.send_json({"type": "status", "text": "Generating speech..."})
            tts_text = response_text[:500]
            detected_lang = _detect_lang(tts_text)
            wav_bytes = await asyncio.to_thread(_generate_tts, tts_text, detected_lang)
            if wav_bytes:
                await websocket.send_bytes(wav_bytes)
            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        pass


def _transcribe(audio_bytes: bytes) -> tuple[str, str]:
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        segments, info = whisper_model.transcribe(tmp.name, beam_size=5, vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments)
    return text, info.language


def _detect_lang(text: str) -> str:
    for c in text:
        if "　" <= c <= "鿿" or "゠" <= c <= "ヿ":
            return "ja"
    return "en"


def _generate_tts(text: str, lang: str) -> bytes:
    pipeline = pipelines.get(lang, pipelines["en"])
    voice = DEFAULT_VOICES.get(lang, "af_heart")
    samples = []
    for _, _, audio in pipeline(text, voice=voice):
        if audio is not None:
            samples.append(audio)
    if not samples:
        return b""
    audio = np.concatenate(samples)
    buf = io.BytesIO()
    sf.write(buf, audio, 24000, format="WAV")
    return buf.getvalue()


# ── Entry point ──

def main():
    config = BusConfig.from_env(name="voice-app")
    global voice_service
    voice_service = VoiceService(
        config,
        fastapi_app=app,
        host="0.0.0.0",
        port=8801,
        ssl_keyfile="key.pem",
        ssl_certfile="cert.pem",
    )
    voice_service.run()


if __name__ == "__main__":
    main()
