"""Saathi's voice: offline Hindi text-to-speech with Piper."""
import io
import re
import threading
import wave
from pathlib import Path

from .settings import MODELS_DIR

HINDI_VOICES = {
    "hi_IN-rohan-medium": "Rohan (male)",
    "hi_IN-pratham-medium": "Pratham (male)",
    "hi_IN-priyamvada-medium": "Priyamvada (female)",
}

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF️‍]")
_MARKDOWN = re.compile(r"[*_#`>|~\[\]]")


def clean_for_speech(text: str) -> str:
    text = _EMOJI.sub("", text or "")
    text = _MARKDOWN.sub("", text)
    text = re.sub(r"\(.*?\)", "", text) if len(text) > 40 else text  # asides read badly aloud
    return re.sub(r"\s+", " ", text).strip()[:600]


class Voice:
    def __init__(self):
        self._voices = {}
        self._lock = threading.Lock()
        self.last_error = ""

    @staticmethod
    def voice_path(name: str) -> Path:
        return MODELS_DIR / "piper" / f"{name}.onnx"

    def available(self, name: str) -> bool:
        path = self.voice_path(name)
        return path.exists() and path.with_suffix(".onnx.json").exists()

    def installed(self) -> list[str]:
        folder = MODELS_DIR / "piper"
        return sorted(p.stem for p in folder.glob("*.onnx")) if folder.exists() else []

    def _load(self, name: str):
        if name not in self._voices:
            from piper import PiperVoice  # imported lazily
            if not self.available(name):
                raise FileNotFoundError(f"Piper voice '{name}' not found. Run: python scripts/setup.py")
            self._voices[name] = PiperVoice.load(str(self.voice_path(name)))
        return self._voices[name]

    def preload(self, cfg: dict) -> None:
        try:
            with self._lock:
                self._load(cfg["voice"])
        except Exception as err:  # noqa: BLE001
            self.last_error = str(err)

    def speak(self, text: str, name: str, speed: float) -> bytes:
        """Return a WAV file (bytes) of the text spoken in Hindi."""
        from piper import SynthesisConfig

        text = clean_for_speech(text)
        if not text:
            raise ValueError("nothing to say")
        # Piper's length_scale stretches time: >1 is slower. speed 0.9 -> 1.11
        syn = SynthesisConfig(length_scale=1.0 / max(speed, 0.5))
        buf = io.BytesIO()
        with self._lock:
            voice = self._load(name)
            with wave.open(buf, "wb") as wav:
                voice.synthesize_wav(text, wav, syn_config=syn)
        return buf.getvalue()
