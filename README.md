# साथी · Saathi

**An offline Hindi voice companion for someone you love.** Saathi looks and feels like a video call: a friendly face, big buttons, and a voice that talks in everyday Hindi. It remembers what you told it last time, passes on messages from family, and shows emergency numbers if something sounds wrong.

Everything runs on one laptop. No accounts, no cloud, no monthly bill, and nothing leaves the house.

![Saathi call screen](docs/call-screen.png)

Built for the [DEV Hacktoberfest Weekend Challenge: Build for a Friend](https://dev.to/challenges/hacktoberfest-weekend-2026-10-01) (October 2–5, 2026).

---

## How it works

```
  her voice ──► Whisper (faster-whisper) ──► Gemma 4 (Ollama) ──► Piper Hindi voice ──► speakers
   (mic)          speech → Hindi text          writes the reply        text → speech
                                                     ▲
                       her profile, family messages, remembered facts (local JSON files)
```

| Part | Open-source piece | Runs on |
|---|---|---|
| Listening | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper, Hindi) | this laptop, CPU |
| Thinking | [Gemma 4](https://deepmind.google/models/gemma/) served by [Ollama](https://ollama.com) | this laptop, GPU or CPU |
| Speaking | [Piper](https://github.com/OHF-Voice/piper1-gpl) with a Hindi voice | this laptop, CPU |
| App | Python + FastAPI, plain HTML/JS | this laptop |

### Things that make it feel like a call, not a chatbot
- **Hands-free.** After Saathi speaks, it starts listening by itself and notices when she has finished talking. She never has to touch a key.
- **Starts talking quickly.** Gemma's reply streams in; each finished sentence is spoken straight away instead of waiting for the whole answer.
- **A face that talks.** The mouth moves with the loudness of the voice, the eyes blink, and the ring around the face shows whether Saathi is speaking, thinking or listening.
- **Big and simple.** Four large buttons with Hindi labels: बोलिए (speak), लिखिए (type), फिर से सुनिए (repeat), कॉल खत्म (end call). Large Devanagari subtitles for everything.
- **It remembers.** After each call, Gemma picks out a few facts worth remembering ("मौसी जी के घुटने में दर्द था"). Next time, Saathi asks how her knee is.
- **Messages from family.** Leave a note on the family page ("I'll video call you on Sunday at 7"), and Saathi passes it on in its own words at the start of the next call.
- **Correct Hindi grammar.** Saathi uses the right verb forms for her (कैसी हैं / कैसे हैं) and for itself (रही हूँ / रहा हूँ), depending on the face you pick.

### Safety, built in
- **Emergency card.** If she mentions chest pain, a fall, trouble breathing or fainting, the screen shows her emergency contact and the local emergency number in huge text. This is a plain keyword check that does not depend on the AI getting it right.
- **Scam card.** Mentions of OTPs, bank PINs, "KYC", AnyDesk or "digital arrest" show a warning not to share anything and to call family first.
- **Honest about what it is.** Saathi says it is a computer companion if asked, never gives medicine advice, and gently encourages her to call family and meet friends. It is meant to keep her company between calls, not to replace anyone.

![Emergency card](docs/safety-card.png)

---

## What you need

- Windows 10/11, Linux or macOS
- 16 GB RAM recommended (8 GB works with the smallest model)
- About 10–15 GB of free disk space
- [Python 3.10–3.12](https://www.python.org/downloads/) (on Windows, tick **"Add python.exe to PATH"** when installing)
- [Ollama](https://ollama.com/download)
- Microsoft Edge or Google Chrome (for the call window)
- A microphone and speakers (any laptop's built-in ones are fine)
- Internet **once**, for the downloads. After that, unplug it.

## Set it up (once, with internet)

1. **Install Ollama** from https://ollama.com/download and open it once. It keeps running quietly in the background.
2. **Get this folder** (download the ZIP from GitHub and unzip it, or `git clone`).
3. **Windows:** double-click `start.bat`.
   **Linux/macOS:** run `./start.sh` in a terminal.

   The first run creates a Python environment, installs everything, then downloads Gemma, Whisper and the Hindi voice. This takes a while (Gemma is several GB). When it finishes, the call window opens.
4. **Open the family page** (small link at the bottom-left, or http://127.0.0.1:8765/family). Fill in her name, how Saathi should address her (मौसी जी, बुआ जी, चाचा जी…), family members, interests and the emergency contact. Press **Save**.
5. Turn off the Wi-Fi and try a call. It should work exactly the same.

<details>
<summary>Manual setup (if you prefer the terminal)</summary>

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python scripts/setup.py                  # downloads Gemma (via Ollama), Whisper, Hindi voice
python server.py --open                  # http://127.0.0.1:8765
```
</details>

## Every day

Double-click `start.bat` (put a shortcut on the desktop), then press the big green **बात शुरू करें** button. That's it.

## Choosing the Gemma model

Change it on the family page (Advanced), or run `python scripts/setup.py --model <tag>`.

| Ollama tag | When to use it |
|---|---|
| `gemma4:e2b` | Older laptops, or no graphics card. Fastest, simplest Hindi. |
| `gemma4:e4b` | **Default.** Good Hindi; comfortable on a laptop with a modern GPU or 16 GB RAM. |
| `gemma4:12b` | The most natural Hindi; needs roughly a 12 GB graphics card. |

Download sizes and speeds vary by machine; try `e4b` first and step down if replies feel slow.

## Hindi voices

| Voice | Sounds like |
|---|---|
| `hi_IN-rohan-medium` | male (default; matches the "Bhaiya" face) |
| `hi_IN-pratham-medium` | male |
| `hi_IN-priyamvada-medium` | female (pair it with the "Didi" face) |

`python scripts/setup.py --all-voices` downloads all three so you can compare them with the **Hear the voice** button. Samples: https://rhasspy.github.io/piper-samples/

If no Piper voice is installed, Saathi falls back to the browser's own Hindi voice (if the computer has one), and always shows subtitles.

## Privacy

Everything Saathi keeps is in the `data/` folder as readable JSON:

- `settings.json`: the profile you filled in
- `history.json`: recent conversation (only the last few hours are used in a call)
- `memories.json`: the facts it remembers (view and delete them on the family page)
- `family_messages.json`: your notes to her

Delete the folder and Saathi forgets everything. The server only listens on `127.0.0.1`, so other devices on the network can't reach it.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Ollama is not running" | Open the Ollama app, then reload the call window. |
| Model not downloaded | `ollama pull gemma4:e4b` or `python scripts/setup.py` |
| Saathi can't hear her | Check the browser allowed the microphone (lock icon in the address bar). Make sure the Whisper model downloaded. Try the `base` model if listening is slow. |
| It cuts her off mid-sentence | She can press the green button again; or speak a little louder. The pause it waits for is `END_SILENCE_MS` in `web/call.js`. |
| Replies are slow | Use `gemma4:e2b`, and keep Ollama running so the model stays loaded. |
| Listening on an NVIDIA GPU | Set "Listening runs on" to NVIDIA GPU (needs CUDA 12 + cuDNN). If it fails, Saathi falls back to CPU. |

## Tests

```bash
pip install pytest
python -m pytest -q
```

The tests run the real server against a small fake Ollama (`tests/fake_ollama.py`), covering streaming replies, greetings with family messages, memory extraction, the emergency and scam cards, and the friendly errors when Ollama or the model is missing.

## Credits and licences

- Saathi's code: MIT (see `LICENSE`).
- [Gemma 4](https://deepmind.google/models/gemma/) by Google DeepMind: Apache 2.0.
- [Ollama](https://github.com/ollama/ollama): MIT.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): MIT; [Whisper](https://github.com/openai/whisper) weights by OpenAI: MIT.
- [Piper](https://github.com/OHF-Voice/piper1-gpl) (`piper-tts`): GPL-3.0. Saathi uses it as a separately installed package.
- Piper Hindi voices: each voice has its own model card and dataset licence in [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices). Some are trained on non-commercial data (e.g. CC BY-NC-SA). Saathi is a personal, non-commercial project; check the model card before any other use.
- [FastAPI](https://github.com/fastapi/fastapi): MIT.

Built with help from an AI coding assistant (Claude).

The repository was created and the project built during the challenge window (October 2–5, 2026). Any commits after the submission deadline are listed below.

### Changes after the deadline
- _(none yet)_
