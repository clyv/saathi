"""One-time setup (needs internet). After this, Saathi works fully offline.

    python scripts/setup.py                   # Gemma + Whisper + the configured Hindi voice
    python scripts/setup.py --all-voices      # also fetch every Hindi voice, to compare them
    python scripts/setup.py --model gemma4:e2b --whisper base   # smaller, for older laptops

What it downloads:
  * Gemma, through your local Ollama        (a few GB; size depends on the model tag)
  * Whisper speech recognition (faster-whisper)  ->  models/whisper/<size>/
  * Piper Hindi voice(s)                          ->  models/piper/
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from saathi import settings                     # noqa: E402
from saathi.voice import HINDI_VOICES          # noqa: E402

OK, BAD, INFO = "  [ok]  ", "  [!!]  ", "  ...   "


def setup_gemma(url: str, model: str) -> bool:
    import httpx

    print(f"\n1. Gemma via Ollama ({model})")
    try:
        tags = httpx.get(url.rstrip("/") + "/api/tags", timeout=5).json()
    except Exception:
        print(BAD + f"Ollama is not running at {url}.")
        print("        Install it from https://ollama.com, open it, then run this script again.")
        return False
    names = [m.get("name") for m in tags.get("models", [])]
    if model in names or f"{model}:latest" in names:
        print(OK + f"{model} is already downloaded.")
        return True
    print(INFO + f"Downloading {model}. This is the big one; it can take a while.")
    last = ""
    try:
        with httpx.stream("POST", url.rstrip("/") + "/api/pull", json={"model": model, "stream": True},
                          timeout=httpx.Timeout(connect=10, read=None, write=30, pool=10)) as resp:
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                if data.get("error"):
                    print("\n" + BAD + data["error"])
                    return False
                status = data.get("status", "")
                if data.get("total") and data.get("completed"):
                    pct = 100 * data["completed"] / data["total"]
                    msg = f"{status} {pct:5.1f}%"
                else:
                    msg = status
                if msg != last:
                    print(f"\r        {msg[:70]:<70}", end="", flush=True)
                    last = msg
    except Exception as err:  # noqa: BLE001
        print("\n" + BAD + f"Download failed: {err}")
        return False
    print("\n" + OK + f"{model} downloaded.")
    return True


def setup_whisper(size: str) -> bool:
    from faster_whisper import download_model

    print(f"\n2. Whisper speech recognition ({size})")
    target = settings.MODELS_DIR / "whisper" / size
    if (target / "model.bin").exists():
        print(OK + f"already in {target}")
        return True
    print(INFO + "Downloading…")
    try:
        download_model(size, output_dir=str(target))
    except Exception as err:  # noqa: BLE001
        print(BAD + f"Download failed: {err}")
        return False
    print(OK + f"saved to {target}")
    return True


def setup_voices(voices: list[str]) -> bool:
    from piper.download_voices import download_voice

    print(f"\n3. Piper Hindi voice{'s' if len(voices) > 1 else ''}")
    target = settings.MODELS_DIR / "piper"
    target.mkdir(parents=True, exist_ok=True)
    ok = True
    for name in voices:
        if (target / f"{name}.onnx").exists() and (target / f"{name}.onnx.json").exists():
            print(OK + f"{name} already downloaded")
            continue
        try:
            download_voice(name, target)
            print(OK + f"{name} saved to {target}")
        except Exception as err:  # noqa: BLE001
            print(BAD + f"{name} failed: {err}")
            ok = False
    return ok


def main() -> int:
    cfg = settings.load()["config"]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=cfg["model"], help=f"Ollama model tag (default {cfg['model']})")
    ap.add_argument("--whisper", default=cfg["stt_model"], help=f"Whisper size (default {cfg['stt_model']})")
    ap.add_argument("--voice", default=cfg["voice"], help=f"Piper voice (default {cfg['voice']})")
    ap.add_argument("--all-voices", action="store_true", help="download every Hindi voice")
    ap.add_argument("--skip-ollama", action="store_true")
    args = ap.parse_args()

    print("Saathi setup. Everything is saved on this computer.")
    results = []
    if not args.skip_ollama:
        results.append(setup_gemma(cfg["ollama_url"], args.model))
    results.append(setup_whisper(args.whisper))
    results.append(setup_voices(list(HINDI_VOICES) if args.all_voices else [args.voice]))

    if args.model != cfg["model"] or args.whisper != cfg["stt_model"] or args.voice != cfg["voice"]:
        settings.save({"config": {"model": args.model, "stt_model": args.whisper, "voice": args.voice}})
        print("\n" + INFO + "Saved these choices as Saathi's settings.")

    if all(results):
        print("\nAll set. You can disconnect from the internet now; Saathi runs fully offline.")
        print("Start it with start.bat (Windows) or ./start.sh (Linux/macOS).")
        return 0
    print("\nSome steps failed (see above). Fix them and run this script again; finished steps are skipped.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
