"""Saathi server. Run:  python server.py   then open http://127.0.0.1:8765

Everything runs on this computer: Gemma through Ollama hears, sees, thinks and remembers;
Piper speaks; Whisper is the fallback for listening.
"""
import argparse
import asyncio
import base64
import binascii
import json
import os
import tempfile
import threading
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from saathi import __version__, brain, memory, safety, settings
from saathi.ears import GEMMA_MAX_SECONDS, Ears, to_wav16k
from saathi.voice import HINDI_VOICES, Voice

ears = Ears()
voice = Voice()

# What has been said since the current call started (for memory extraction).
SESSION = {"transcript": [], "user_turns": 0, "extracted_upto": 0}
_memory_lock = asyncio.Lock()
_background: set[asyncio.Task] = set()    # keep references so tasks are not garbage-collected


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = settings.load()["config"]
    _spawn(brain.warm_up(cfg))                                    # load Gemma into memory
    if cfg["stt_engine"] == "whisper":                            # otherwise Whisper loads only if needed
        threading.Thread(target=ears.preload, args=(cfg,), daemon=True).start()
    threading.Thread(target=voice.preload, args=(cfg,), daemon=True).start()
    yield


app = FastAPI(title="Saathi", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=settings.WEB_DIR), name="static")


# -------------------------------------------------------------------- pages ----
@app.get("/")
def call_screen():
    return FileResponse(settings.WEB_DIR / "index.html")


@app.get("/family")
def family_page():
    return FileResponse(settings.WEB_DIR / "family.html")


# ----------------------------------------------------------------- settings ----
@app.get("/api/settings")
def get_settings():
    s = settings.load()
    return {**s, "voices": HINDI_VOICES, "voices_installed": voice.installed(),
            "address": settings.address_of(s["profile"])}


@app.put("/api/settings")
def put_settings(body: dict):
    saved = settings.save(body)
    threading.Thread(target=voice.preload, args=(saved["config"],), daemon=True).start()
    return {**saved, "voices": HINDI_VOICES, "voices_installed": voice.installed(),
            "address": settings.address_of(saved["profile"])}


@app.get("/api/status")
async def get_status():
    cfg = settings.load()["config"]
    gemma = await brain.status(cfg)
    whisper = ears.available(cfg["stt_model"])
    gemma_hears = cfg["stt_engine"] == "gemma" and gemma["hears"]
    return {
        "ollama": gemma,
        "stt": {"engine": "gemma" if gemma_hears else "whisper", "chosen": cfg["stt_engine"],
                "gemma_hears": gemma["hears"], "whisper": whisper,
                "model": cfg["stt_model"], "device": cfg["stt_device"],
                "available": gemma_hears or whisper, "note": ears.last_error},
        "tts": {"voice": cfg["voice"], "available": voice.available(cfg["voice"]),
                "installed": voice.installed(), "note": voice.last_error},
        "data_dir": str(settings.DATA_DIR),
        "version": __version__,
    }


@app.post("/api/warmup")
async def warmup():
    """The call screen asks for this when it opens, and every few minutes while it stays open."""
    _spawn(brain.warm_up(settings.load()["config"]))
    return {"ok": True}


# --------------------------------------------------------------------- chat ----
def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _alternate(messages: list[dict]) -> list[dict]:
    """Merge back-to-back messages from the same role (some chat templates require alternation)."""
    out = []
    for m in messages:
        if out and out[-1]["role"] == m["role"] and m["role"] != "system":
            merged = {**out[-1], "content": out[-1]["content"] + "\n" + m["content"]}
            if m.get("images"):
                merged["images"] = out[-1].get("images", []) + m["images"]
            out[-1] = merged
        else:
            out.append(dict(m))
    return out


def _relevant_family_messages() -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    return [m for m in memory.family_messages() if not m.get("delivered") or m["delivered"] >= cutoff]


def _alert_payload(kind: str, profile: dict) -> dict:
    return {"type": "alert", "kind": kind,
            "contact": profile.get("emergency_contact_name", ""),
            "phone": profile.get("emergency_contact_phone", ""),
            "number": profile.get("emergency_number") or "112"}


async def _extract_memories(transcript: list[dict]) -> None:
    if sum(1 for m in transcript if m["role"] == "user") < 1:
        return
    s = settings.load()
    async with _memory_lock:
        try:
            result = await brain.complete_json(
                s["config"], brain.memory_request(s["profile"], transcript, memory.memories()))
            facts = result.get("memories", []) if isinstance(result, dict) else []
            memory.add_memories([f for f in facts if isinstance(f, str)][:3])
        except Exception:  # noqa: BLE001 - memory is a nice-to-have, never break the call
            pass


def _maybe_extract(cfg: dict, force: bool = False) -> None:
    start = SESSION["extracted_upto"]
    chunk = SESSION["transcript"][start:]
    user_turns = sum(1 for m in chunk if m["role"] == "user")
    if user_turns and (force or user_turns >= cfg["memory_every_turns"]):
        SESSION["extracted_upto"] = len(SESSION["transcript"])
        _spawn(_extract_memories(chunk))


def _reply(user_text: str = "", greeting: bool = False, image: str | None = None) -> StreamingResponse:
    s = settings.load()
    cfg, profile = s["config"], s["profile"]
    family = _relevant_family_messages()
    new_ids = [m["id"] for m in family if not m.get("delivered")]

    messages = [{"role": "system",
                 "content": brain.system_prompt(profile, memory.memories(), family, datetime.now())}]
    messages += memory.recent_messages(cfg["history_messages"], cfg["history_hours"])
    alert = safety.check(user_text) if user_text else None
    if image:
        # The picture goes to Gemma for this turn only; history keeps a note, never the image.
        messages.append({"role": "user", "content": brain.showing_note(profile, user_text), "images": [image]})
    elif user_text:
        # When the keyword check fires, Gemma is told too, so its voice matches the card on screen.
        note = f"\n\n{brain.alert_note(alert, profile)}" if alert else ""
        messages.append({"role": "user", "content": user_text + note})
    if greeting:
        today = datetime.now().date()
        follow_up = brain.memory_to_ask_about(memory.memories(), today)
        messages.append({"role": "user",
                         "content": brain.greeting_instruction(profile, bool(new_ids), follow_up, today)})
    messages = _alternate(messages)
    said = f"{brain.SHOWED_PICTURE} {user_text}".strip() if image else user_text

    async def generate():
        if alert:
            yield _line(_alert_payload(alert, profile))
        pieces = []
        try:
            async for piece in brain.stream_reply(cfg, messages):
                pieces.append(piece)
                yield _line({"type": "delta", "text": piece})
        except brain.BrainError as err:
            yield _line({"type": "error", "code": err.code, "detail": err.detail[:400]})
            return
        reply = "".join(pieces).strip()
        if said:
            memory.add_message("user", said)
            SESSION["transcript"].append({"role": "user", "content": said})
        memory.add_message("assistant", reply)
        SESSION["transcript"].append({"role": "assistant", "content": reply})
        if greeting:
            memory.mark_delivered(new_ids)
        _maybe_extract(cfg)
        # A picture of a fraud SMS has no words of hers to check, so check what Gemma read in it.
        if image and not alert and safety.check(reply) == "scam":
            yield _line(_alert_payload("scam", profile))
        yield _line({"type": "done", "text": reply})

    return StreamingResponse(generate(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ChatIn(BaseModel):
    text: str = ""
    image: str | None = None      # a camera snapshot: base64 JPEG (a data: URL is fine too)


def _clean_image(image: str | None) -> str | None:
    if not image:
        return None
    b64 = image.split(",", 1)[1] if image.startswith("data:") else image
    if len(b64) > 8_000_000:
        raise HTTPException(413, "picture too large")
    try:
        base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as err:
        raise HTTPException(400, "picture is not valid base64") from err
    return b64


@app.post("/api/greet")
async def greet():
    if SESSION["transcript"]:
        _maybe_extract(settings.load()["config"], force=True)
    SESSION.update(transcript=[], user_turns=0, extracted_upto=0)
    return _reply(greeting=True)


@app.post("/api/chat")
async def chat(body: ChatIn):
    text = body.text.strip()[:2000]
    image = _clean_image(body.image)
    if not text and not image:
        raise HTTPException(400, "empty message")
    return _reply(user_text=text, image=image)


@app.post("/api/session/end")
async def end_session():
    _maybe_extract(settings.load()["config"], force=True)
    return {"ok": True}


# ------------------------------------------------------------ ears + voice ----
async def _hear(path: str, cfg: dict) -> tuple[str, str]:
    """Turn her recording into text. Returns (text, which engine heard it)."""
    whisper = ears.available(cfg["stt_model"])
    caps = await brain.capabilities(cfg) if cfg["stt_engine"] == "gemma" else []
    if caps is None and not whisper:
        raise RuntimeError("Ollama is not reachable right now")   # a one-off failure, not "can't hear"
    if caps and "audio" in caps:
        try:
            wav, seconds = await asyncio.to_thread(to_wav16k, path)
            if seconds <= GEMMA_MAX_SECONDS or not whisper:
                return await brain.transcribe(cfg, wav), "gemma"
        except Exception as err:  # noqa: BLE001 - fall back to Whisper if it is there
            if not whisper:
                raise
            ears.last_error = f"Gemma could not hear a clip ({str(err)[:120]}); Whisper listened instead."
    if not whisper:
        raise LookupError("Nothing can listen: the Gemma model has no audio input and Whisper is not "
                          "downloaded. Run: python scripts/setup.py")
    return await asyncio.to_thread(ears.transcribe, path, cfg), "whisper"


@app.post("/api/listen")
async def listen(audio: UploadFile = File(...)):
    cfg = settings.load()["config"]
    suffix = ".webm" if "webm" in (audio.content_type or "") else ".ogg" if "ogg" in (audio.content_type or "") else ".wav"
    data = await audio.read()
    if len(data) < 1000:
        return {"text": ""}
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        text, engine = await _hear(path, cfg)
    except LookupError as err:
        return JSONResponse({"error": "stt_unavailable", "detail": str(err)}, status_code=503)
    except Exception as err:  # noqa: BLE001
        return JSONResponse({"error": "stt_failed", "detail": str(err)[:300]}, status_code=503)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return {"text": text, "engine": engine}


class SpeakIn(BaseModel):
    text: str
    voice: str | None = None
    speed: float | None = None


@app.post("/api/speak")
async def speak(body: SpeakIn):
    cfg = settings.load()["config"]
    name = body.voice or cfg["voice"]
    if not voice.available(name):
        return JSONResponse({"fallback": True, "detail": f"voice {name} not installed"}, status_code=503)
    try:
        wav = await asyncio.to_thread(voice.speak, body.text, name, body.speed or cfg["speech_speed"])
    except ValueError:
        return Response(status_code=204)
    except Exception as err:  # noqa: BLE001
        return JSONResponse({"fallback": True, "detail": str(err)[:300]}, status_code=503)
    return Response(content=wav, media_type="audio/wav")


# ---------------------------------------------------- family data endpoints ----
class FamilyMessageIn(BaseModel):
    from_name: str
    relation: str = ""
    text: str


@app.get("/api/family-messages")
def list_family_messages():
    return memory.family_messages()


@app.post("/api/family-messages")
def create_family_message(body: FamilyMessageIn):
    if not body.from_name.strip() or not body.text.strip():
        raise HTTPException(400, "name and message are required")
    return memory.add_family_message(body.from_name, body.relation, body.text)


@app.delete("/api/family-messages/{message_id}")
def remove_family_message(message_id: str):
    return {"deleted": memory.delete_family_message(message_id)}


@app.get("/api/memories")
def list_memories():
    return memory.memories()


@app.delete("/api/memories/{memory_id}")
def remove_memory(memory_id: str):
    return {"deleted": memory.delete_memory(memory_id)}


@app.post("/api/history/clear")
def clear_history():
    memory.clear_history()
    SESSION.update(transcript=[], user_turns=0, extracted_upto=0)
    return {"ok": True}


# --------------------------------------------------------------------- main ----
def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Run Saathi")
    parser.add_argument("--host", default=os.environ.get("SAATHI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SAATHI_PORT", "8765")))
    parser.add_argument("--open", action="store_true", help="open the call screen in the browser")
    args = parser.parse_args()
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}/")).start()
    print(f"\n  Saathi is running:  http://127.0.0.1:{args.port}/\n"
          f"  Family settings:    http://127.0.0.1:{args.port}/family\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
