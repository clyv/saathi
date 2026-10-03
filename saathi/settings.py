"""Settings and file locations. Everything lives in ./data and ./models on this computer."""
import copy
import json
import os
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SAATHI_DATA_DIR", ROOT / "data"))
MODELS_DIR = Path(os.environ.get("SAATHI_MODELS_DIR", ROOT / "models"))
WEB_DIR = ROOT / "web"

# Who the companion is talking to. Filled in by a family member on the settings page.
DEFAULT_PROFILE = {
    "companion_name": "साथी",
    "avatar": "bhaiya",              # bhaiya | didi  (match it with a male or female voice)
    "person_name": "",               # e.g. "Sunita"
    "address_as": "",                # how to address her, e.g. "मौसी जी"
    "person_gender": "female",       # female | male (Hindi grammar depends on it)
    "about": "",                     # where she lives, her life, what matters to her
    "family": [],                    # [{"name", "relation", "lives_in", "note"}]
    "interests": "",
    "daily_routine": "",
    "avoid_topics": "",
    "emergency_contact_name": "",
    "emergency_contact_phone": "",
    "emergency_number": "112",       # India: 112. UAE: 999 (police) / 998 (ambulance)
}

# How the software runs.
DEFAULT_CONFIG = {
    "ollama_url": "http://127.0.0.1:11434",
    "model": "gemma4:e4b",
    "temperature": 0.7,
    "num_ctx": 8192,
    "keep_alive": "30m",             # Ollama keeps Gemma loaded this long after the call window closes
    "history_hours": 6,              # raw chat history older than this is left out of the prompt
    "history_messages": 14,          # at most this many recent messages go into the prompt
    "stt_model": "small",            # faster-whisper size: base (fast) | small | medium (better)
    "stt_device": "cpu",             # cpu (reliable everywhere) | cuda (needs CUDA + cuDNN)
    "voice": "hi_IN-rohan-medium",   # Piper voice; see README for the Hindi options
    "speech_speed": 0.9,             # 1.0 = normal; lower is slower and easier to follow
    "auto_listen": True,             # start listening as soon as Saathi stops speaking
    "text_size": "large",            # normal | large | huge
    "memory_every_turns": 6,         # extract memories every N things she says
}

_SETTINGS_FILE = DATA_DIR / "settings.json"
_lock = threading.Lock()


def _merge(defaults: dict, saved: dict) -> dict:
    merged = copy.deepcopy(defaults)
    for key, value in (saved or {}).items():
        if key in merged:
            merged[key] = value
    return merged


def load() -> dict:
    """Return {"profile": {...}, "config": {...}} with defaults filled in."""
    saved = {}
    if _SETTINGS_FILE.exists():
        try:
            saved = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = {}
    settings = {
        "profile": _merge(DEFAULT_PROFILE, saved.get("profile")),
        "config": _merge(DEFAULT_CONFIG, saved.get("config")),
    }
    # Environment overrides (handy for testing and for the launcher scripts).
    if os.environ.get("SAATHI_OLLAMA_URL"):
        settings["config"]["ollama_url"] = os.environ["SAATHI_OLLAMA_URL"]
    if os.environ.get("SAATHI_MODEL"):
        settings["config"]["model"] = os.environ["SAATHI_MODEL"]
    return settings


def save(new: dict) -> dict:
    """Validate and save settings sent from the family page. Unknown keys are ignored."""
    current = load()
    profile = _merge(current["profile"], new.get("profile", {}))
    config = _merge(current["config"], new.get("config", {}))

    profile["family"] = [
        {k: str(member.get(k, "")).strip()[:200] for k in ("name", "relation", "lives_in", "note")}
        for member in (profile.get("family") or [])[:20]
        if isinstance(member, dict) and str(member.get("name", "")).strip()
    ]
    for key, value in list(profile.items()):
        if key != "family":
            profile[key] = str(value or "").strip()[:2000]
    if profile["person_gender"] not in ("female", "male"):
        profile["person_gender"] = "female"
    if profile["avatar"] not in ("didi", "bhaiya"):
        profile["avatar"] = "bhaiya"

    config["temperature"] = min(max(float(config["temperature"]), 0.0), 1.5)
    config["num_ctx"] = int(config["num_ctx"])
    config["speech_speed"] = min(max(float(config["speech_speed"]), 0.6), 1.4)
    config["auto_listen"] = bool(config["auto_listen"])
    config["history_messages"] = min(max(int(config["history_messages"]), 2), 40)
    config["memory_every_turns"] = min(max(int(config["memory_every_turns"]), 2), 50)
    if config["stt_device"] not in ("cpu", "cuda"):
        config["stt_device"] = "cpu"
    if not re.fullmatch(r"-1|\d+[smh]?", str(config["keep_alive"]).strip()):
        config["keep_alive"] = DEFAULT_CONFIG["keep_alive"]
    config["keep_alive"] = str(config["keep_alive"]).strip()
    if config["text_size"] not in ("normal", "large", "huge"):
        config["text_size"] = "large"

    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"profile": profile, "config": config}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(_SETTINGS_FILE)
    return load()


def address_of(profile: dict) -> str:
    """How Saathi addresses her: 'मौसी जी', else 'Sunita जी', else 'आप'."""
    if profile.get("address_as"):
        return profile["address_as"]
    if profile.get("person_name"):
        return f"{profile['person_name']} जी"
    return "आप"
