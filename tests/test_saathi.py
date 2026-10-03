"""End-to-end tests against a fake Ollama.   Run:  python -m pytest -q"""
import base64
import io
import json
import math
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import wave
from datetime import date
from pathlib import Path

import pytest
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _free_port()
os.environ["SAATHI_OLLAMA_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["SAATHI_DATA_DIR"] = tempfile.mkdtemp(prefix="saathi-data-")
os.environ["SAATHI_MODELS_DIR"] = tempfile.mkdtemp(prefix="saathi-models-")

import fake_ollama  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from saathi import brain, safety  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def fake():
    srv = uvicorn.Server(uvicorn.Config(fake_ollama.app, host="127.0.0.1", port=PORT, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield
    srv.should_exit = True


@pytest.fixture(scope="module")
def client(fake):
    with TestClient(server.app) as c:
        yield c


def events(resp) -> list[dict]:
    return [json.loads(line) for line in resp.text.splitlines() if line.strip()]


def test_status_sees_gemma(client):
    st = client.get("/api/status").json()
    assert st["ollama"]["reachable"] and st["ollama"]["model_present"]
    assert st["ollama"]["hears"] and st["ollama"]["sees"]
    # No Whisper downloaded, but Gemma can hear, so listening works.
    assert st["stt"]["engine"] == "gemma" and st["stt"]["available"] is True
    assert st["stt"]["whisper"] is False and st["tts"]["available"] is False


def test_warm_up_loads_gemma_the_same_way_chat_does(client):
    for _ in range(50):
        if fake_ollama.WARMUPS:
            break
        time.sleep(0.05)
    warm = fake_ollama.WARMUPS[0]
    # A different num_ctx makes Ollama reload the whole model (~28 s on a laptop GPU).
    assert warm["options"]["num_ctx"] == 8192 and warm["keep_alive"] == "30m"
    assert client.post("/api/warmup").json() == {"ok": True}
    assert client.get("/api/status").json()["ollama"]["loaded"] is True


def test_settings_roundtrip(client):
    body = {"profile": {"person_name": "Sunita", "address_as": "मौसी जी", "person_gender": "female",
                        "family": [{"name": "Clivin", "relation": "nephew", "lives_in": "Dubai"}, {"name": ""}],
                        "emergency_contact_name": "Rahul", "emergency_contact_phone": "+91 98765 43210"},
            "config": {"speech_speed": 5, "auto_listen": False, "unknown_key": 1,
                       "keep_alive": "forever", "stt_engine": "magic"}}
    saved = client.put("/api/settings", json=body).json()
    assert saved["address"] == "मौसी जी"
    assert len(saved["profile"]["family"]) == 1               # empty rows dropped
    assert saved["config"]["speech_speed"] == 1.4               # clamped
    assert "unknown_key" not in saved["config"]
    assert saved["config"]["keep_alive"] == "30m" and saved["config"]["stt_engine"] == "gemma"


def test_greeting_passes_on_family_message(client):
    msg = client.post("/api/family-messages",
                      json={"from_name": "Clivin", "relation": "nephew", "text": "Sunday 7 baje video call karunga"}).json()
    resp = client.post("/api/greet")
    evs = events(resp)
    assert evs[-1]["type"] == "done" and "नमस्ते" in evs[-1]["text"]
    system = fake_ollama.REQUESTS[-1]["messages"][0]["content"]
    assert "मौसी जी" in system and "Sunday 7 baje" in system and "NEW, not told yet" in system
    assert "feminine forms when speaking to her" in system      # how to address her
    assert "masculine verb forms for yourself" in system        # default face is Bhaiya (male voice)
    delivered = {m["id"]: m["delivered"] for m in client.get("/api/family-messages").json()}
    assert delivered[msg["id"]]                                   # marked as told


def test_chat_streams_and_saves_history(client):
    evs = events(client.post("/api/chat", json={"text": "आज मैंने आलू के पराठे बनाए"}))
    assert [e["type"] for e in evs].count("delta") > 3
    last = fake_ollama.REQUESTS[-1]["messages"]
    assert last[-1] == {"role": "user", "content": "आज मैंने आलू के पराठे बनाए"}
    roles = [m["role"] for m in last[1:]]
    assert all(a != b for a, b in zip(roles, roles[1:]))          # strictly alternating


def test_emergency_alert_comes_first(client):
    evs = events(client.post("/api/chat", json={"text": "मेरे सीने में दर्द हो रहा है"}))
    assert evs[0]["type"] == "alert" and evs[0]["kind"] == "emergency"
    assert evs[0]["phone"] == "+91 98765 43210"
    # Gemma is told as well, so what it says matches the card; history keeps only her words.
    said = fake_ollama.REQUESTS[-1]["messages"][-1]["content"]
    assert said.startswith("मेरे सीने में दर्द हो रहा है") and "+91 98765 43210" in said and "112" in said
    assert server.memory.recent_messages(40, 1)[-2]["content"] == "मेरे सीने में दर्द हो रहा है"


def test_safety_keywords():
    assert safety.check("कल मैं बाथरूम में गिर गई थी") == "emergency"
    assert safety.check("साँस लेने में तकलीफ़ है") == "emergency"        # chandrabindu + nukta variants
    assert safety.check("बैंक से फोन आया था, OTP मांग रहे थे") == "scam"
    assert safety.check("आज मौसम बहुत अच्छा है") is None


def test_memories_are_extracted_after_call(client):
    client.post("/api/session/end")
    for _ in range(60):
        mems = client.get("/api/memories").json()
        if mems:
            break
        time.sleep(0.1)
    assert any("पराठे" in m["text"] for m in mems)
    client.delete(f"/api/memories/{mems[0]['id']}")
    assert len(client.get("/api/memories").json()) == len(mems) - 1


def _tone_wav(seconds: float = 1.0, rate: int = 48000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


def test_gemma_hears_her(client):
    r = client.post("/api/listen", files={"audio": ("speech.wav", _tone_wav(), "audio/wav")})
    assert r.json() == {"text": fake_ollama.HEARD, "engine": "gemma"}
    req = fake_ollama.REQUESTS[-1]
    assert "speech-to-text" in req["messages"][0]["content"]       # instruction in the system turn
    sent = base64.b64decode(req["messages"][1]["images"][0])
    with wave.open(io.BytesIO(sent)) as w:                         # resampled for Gemma
        assert (w.getframerate(), w.getnchannels()) == (16000, 1)
        assert abs(w.getnframes() - 16000) < 400
    assert req["options"]["num_ctx"] == 8192


def test_transcript_cleanup():
    assert brain.clean_transcript("-") == ""
    assert brain.clean_transcript(" — ") == ""
    assert brain.clean_transcript("transcribe this audio exactly as spoken in devanagari script") == ""
    assert brain.clean_transcript("आज मैंने फ़ोन पर Rahul से बात की") == "आज मैंने फ़ोन पर Rahul से बात की"


def test_speech_endpoints_fall_back_cleanly(client):
    r = client.post("/api/speak", json={"text": "नमस्ते"})
    assert r.status_code == 503 and r.json()["fallback"] is True
    r = client.post("/api/listen", files={"audio": ("a.webm", b"x" * 2000, "audio/webm")})
    assert r.status_code == 503 and r.json()["error"] == "stt_failed"     # garbage audio, no Whisper backup
    client.put("/api/settings", json={"config": {"stt_engine": "whisper"}})
    r = client.post("/api/listen", files={"audio": ("speech.wav", _tone_wav(), "audio/wav")})
    client.put("/api/settings", json={"config": {"stt_engine": "gemma"}})
    assert r.status_code == 503 and r.json()["error"] == "stt_unavailable"



def test_memories_and_messages_get_relative_dates():
    today = date(2026, 10, 3)
    days = ("2026-10-03", "2026-10-02", "2026-10-01", "2026-09-28", "2026-09-24", "2026-09-10", "2026-08-20")
    assert [brain.how_long_ago(d, today) for d in days] == [
        "आज", "कल", "परसों", "5 दिन पहले", "पिछले हफ़्ते", "3 हफ़्ते पहले", "पिछले महीने"]
    prompt = brain.system_prompt({}, [{"date": "2026-10-02", "text": "घुटने में दर्द था।"}], [],
                                 brain.datetime(2026, 10, 3, 18, 0))
    assert "- (कल) घुटने में दर्द था।" in prompt
    assert "cannot play songs" in prompt                          # it once offered to play music


def test_retries_without_think_for_older_models(client):
    client.put("/api/settings", json={"config": {"model": "nothink-model"}})
    os.environ.pop("SAATHI_MODEL", None)
    evs = events(client.post("/api/chat", json={"text": "कैसे हो"}))
    assert evs[-1]["type"] == "done"
    assert "think" not in fake_ollama.REQUESTS[-1]


def test_friendly_errors(client):
    client.put("/api/settings", json={"config": {"model": "missing-model"}})
    evs = events(client.post("/api/chat", json={"text": "हेलो"}))
    assert evs[-1]["type"] == "error" and evs[-1]["code"] == "model_missing"
    client.put("/api/settings", json={"config": {"model": "gemma4:e4b"}})
    old = os.environ["SAATHI_OLLAMA_URL"]
    os.environ["SAATHI_OLLAMA_URL"] = f"http://127.0.0.1:{_free_port()}"
    evs = events(client.post("/api/chat", json={"text": "हेलो"}))
    # Ollama being down is a one-off listening failure, not "this computer can't listen".
    heard = client.post("/api/listen", files={"audio": ("speech.wav", _tone_wav(), "audio/wav")}).json()
    os.environ["SAATHI_OLLAMA_URL"] = old
    assert evs[-1]["code"] == "ollama_offline"
    assert heard["error"] == "stt_failed"


def test_keep_alive_is_sent_the_way_ollama_reads_it():
    assert brain._keep_alive({"keep_alive": "30m"}) == "30m"
    assert brain._keep_alive({"keep_alive": "-1"}) == -1          # forever, as a number
