"""End-to-end tests against a fake Ollama.   Run:  python -m pytest -q"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
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
from saathi import safety  # noqa: E402


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
    assert st["stt"]["available"] is False and st["tts"]["available"] is False


def test_settings_roundtrip(client):
    body = {"profile": {"person_name": "Sunita", "address_as": "मौसी जी", "person_gender": "female",
                        "family": [{"name": "Clivin", "relation": "nephew", "lives_in": "Dubai"}, {"name": ""}],
                        "emergency_contact_name": "Rahul", "emergency_contact_phone": "+91 98765 43210"},
            "config": {"speech_speed": 5, "auto_listen": False, "unknown_key": 1}}
    saved = client.put("/api/settings", json=body).json()
    assert saved["address"] == "मौसी जी"
    assert len(saved["profile"]["family"]) == 1               # empty rows dropped
    assert saved["config"]["speech_speed"] == 1.4               # clamped
    assert "unknown_key" not in saved["config"]


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


def test_speech_endpoints_fall_back_cleanly(client):
    r = client.post("/api/speak", json={"text": "नमस्ते"})
    assert r.status_code == 503 and r.json()["fallback"] is True
    r = client.post("/api/listen", files={"audio": ("a.webm", b"x" * 2000, "audio/webm")})
    assert r.status_code == 503 and r.json()["error"] == "stt_unavailable"


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
    os.environ["SAATHI_OLLAMA_URL"] = old
    assert evs[-1]["code"] == "ollama_offline"
