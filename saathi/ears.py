"""Saathi's ears: offline Hindi speech-to-text.

By default Gemma hears her directly (see brain.transcribe); this file turns the browser's
recording into the WAV Gemma accepts. faster-whisper (open-source Whisper) is the fallback,
for models without audio input or if Gemma's hearing fails.
"""
import io
import threading
import wave
from pathlib import Path

from .settings import MODELS_DIR

GEMMA_MAX_SECONDS = 30     # Gemma's audio input is made for clips up to about 30 seconds


def to_wav16k(audio_path: str) -> tuple[bytes, float]:
    """Decode any recording (the browser sends WebM/Opus) to 16 kHz mono 16-bit WAV.

    Returns (wav bytes, duration in seconds).
    """
    import av  # installed with faster-whisper

    out = io.BytesIO()
    samples = 0
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    with av.open(audio_path) as container, wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        frames = [f for frame in container.decode(audio=0) for f in resampler.resample(frame)]
        frames += resampler.resample(None)          # flush what the resampler is holding
        for f in frames:
            wav.writeframes(bytes(f.planes[0])[:f.samples * 2])
            samples += f.samples
    return out.getvalue(), samples / 16000

# Whisper sometimes "hears" these on silence or noise. Ignore them when they are all it heard.
_PHANTOMS = {"धन्यवाद", "धन्यवाद।", "शुक्रिया", "thank you", "thanks for watching",
             "subtitles by", "सब्सक्राइब", "please subscribe"}


class Ears:
    def __init__(self):
        self._model = None
        self._key = None
        self._lock = threading.Lock()
        self.last_error = ""

    @staticmethod
    def model_dir(size: str) -> Path:
        return MODELS_DIR / "whisper" / size

    def available(self, size: str) -> bool:
        return (self.model_dir(size) / "model.bin").exists()

    def _load(self, size: str, device: str):
        from faster_whisper import WhisperModel  # imported lazily: slow import

        key = (size, device)
        if self._model is not None and self._key == key:
            return self._model
        if not self.available(size):
            raise FileNotFoundError(
                f"Whisper model '{size}' not found in {self.model_dir(size)}. Run: python scripts/setup.py")
        compute = "float16" if device == "cuda" else "int8"
        try:
            self._model = WhisperModel(str(self.model_dir(size)), device=device, compute_type=compute)
        except Exception as err:  # noqa: BLE001 - e.g. CUDA libraries missing
            if device == "cpu":
                raise
            self.last_error = f"CUDA failed ({err}); using CPU instead"
            self._model = WhisperModel(str(self.model_dir(size)), device="cpu", compute_type="int8")
        self._key = key
        return self._model

    def preload(self, cfg: dict) -> None:
        try:
            with self._lock:
                self._load(cfg["stt_model"], cfg["stt_device"])
        except Exception as err:  # noqa: BLE001
            self.last_error = str(err)

    def transcribe(self, audio_path: str, cfg: dict) -> str:
        try:
            return self._transcribe(audio_path, cfg, cfg["stt_device"])
        except Exception as err:  # noqa: BLE001 - CUDA can fail only once real work starts
            if cfg["stt_device"] == "cpu":
                raise
            self.last_error = f"GPU listening failed ({err}); using CPU instead"
            with self._lock:
                self._model = None
            return self._transcribe(audio_path, cfg, "cpu")

    def _transcribe(self, audio_path: str, cfg: dict, device: str) -> str:
        with self._lock:
            model = self._load(cfg["stt_model"], device)
            segments, _info = model.transcribe(
                audio_path,
                language="hi",
                beam_size=1 if device == "cpu" else 5,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt="नमस्ते। आज मौसम अच्छा है, खाना बन गया है।",  # nudges output to Devanagari
            )
            parts = [s.text.strip() for s in segments
                     if s.no_speech_prob < 0.6 and s.avg_logprob > -1.2 and s.text.strip()]
        text = " ".join(parts).strip()
        if text.lower().strip(" .।!") in {p.strip(" .।!") for p in _PHANTOMS}:
            return ""
        return text
