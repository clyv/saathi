"""Local storage: chat history, remembered facts and messages from family.

Plain JSON files in ./data, so the family can see (and delete) everything Saathi keeps.
"""
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .settings import DATA_DIR

_lock = threading.Lock()
MAX_HISTORY = 400
MAX_MEMORIES = 80


def _path(name: str) -> Path:
    return DATA_DIR / name


def _read_json(name: str, default):
    path = _path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(name: str, value) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(name)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- history ----
def add_message(role: str, content: str) -> None:
    content = (content or "").strip()
    if not content:
        return
    with _lock:
        history = _read_json("history.json", [])
        history.append({"role": role, "content": content, "ts": time.time()})
        _write_json("history.json", history[-MAX_HISTORY:])


def recent_messages(max_messages: int, max_age_hours: float) -> list[dict]:
    cutoff = time.time() - max_age_hours * 3600
    history = [m for m in _read_json("history.json", []) if m.get("ts", 0) >= cutoff]
    return [{"role": m["role"], "content": m["content"]} for m in history[-max_messages:]]


def clear_history() -> None:
    with _lock:
        _write_json("history.json", [])


# --------------------------------------------------------------- memories ----
def memories() -> list[dict]:
    return _read_json("memories.json", [])


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def add_memories(texts: list[str]) -> list[dict]:
    """Add new facts, skipping near-duplicates. Returns what was actually added."""
    added = []
    with _lock:
        items = _read_json("memories.json", [])
        seen = {_norm(m["text"]) for m in items}
        for text in texts:
            text = " ".join(str(text).split())[:240]
            key = _norm(text)
            if len(key) < 6 or key in seen:
                continue
            item = {"id": uuid.uuid4().hex[:10], "text": text, "date": _today()}
            items.append(item)
            added.append(item)
            seen.add(key)
        _write_json("memories.json", items[-MAX_MEMORIES:])
    return added


def delete_memory(memory_id: str) -> bool:
    with _lock:
        items = _read_json("memories.json", [])
        kept = [m for m in items if m["id"] != memory_id]
        _write_json("memories.json", kept)
    return len(kept) != len(items)


# -------------------------------------------------------- family messages ----
def family_messages() -> list[dict]:
    return _read_json("family_messages.json", [])


def add_family_message(from_name: str, relation: str, text: str) -> dict:
    item = {
        "id": uuid.uuid4().hex[:10],
        "from_name": from_name.strip()[:80],
        "relation": relation.strip()[:80],
        "text": text.strip()[:600],
        "created": _today(),
        "delivered": None,
    }
    with _lock:
        items = _read_json("family_messages.json", [])
        items.append(item)
        _write_json("family_messages.json", items[-50:])
    return item


def mark_delivered(ids: list[str]) -> None:
    if not ids:
        return
    with _lock:
        items = _read_json("family_messages.json", [])
        for item in items:
            if item["id"] in ids and not item.get("delivered"):
                item["delivered"] = _today()
        _write_json("family_messages.json", items)


def delete_family_message(message_id: str) -> bool:
    with _lock:
        items = _read_json("family_messages.json", [])
        kept = [m for m in items if m["id"] != message_id]
        _write_json("family_messages.json", kept)
    return len(kept) != len(items)
