"""Saathi's brain: builds the prompt and talks to Gemma through a local Ollama server.

Gemma does every "thinking" job: it hears her (audio in), looks at what she shows the camera
(image in), talks with her, and decides what to remember.

Nothing here calls the internet. Ollama runs on the same laptop (http://127.0.0.1:11434).
"""
import base64
import json
import re
from datetime import date, datetime

import httpx

from .settings import address_of

DAYS = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]
MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त",
          "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


class BrainError(Exception):
    """code is one of: ollama_offline, model_missing, ollama_error."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def part_of_day(hour: int) -> str:
    if 4 <= hour < 12:
        return "सुबह"
    if 12 <= hour < 16:
        return "दोपहर"
    if 16 <= hour < 20:
        return "शाम"
    return "रात"


def hindi_now(now: datetime) -> str:
    return (f"{DAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year}, "
            f"{now.strftime('%I:%M %p').lstrip('0')} ({part_of_day(now.hour)})")


def how_long_ago(day: str, today: date) -> str:
    """'2026-10-01' -> 'परसों'. A small model handles 'two days ago' far better than raw dates."""
    try:
        days = (today - date.fromisoformat(day)).days
    except (TypeError, ValueError):
        return day or ""
    if days <= 0:
        return "आज"
    if days == 1:
        return "कल"
    if days == 2:
        return "परसों"
    if days < 7:
        return f"{days} दिन पहले"
    if days < 14:
        return "पिछले हफ़्ते"
    if days < 30:
        return f"{days // 7} हफ़्ते पहले"
    if days < 60:
        return "पिछले महीने"
    return f"{days // 30} महीने पहले"


# ------------------------------------------------------------------ prompts ----
def pronouns(profile: dict) -> dict:
    if profile.get("person_gender") == "male":
        return {"she": "he", "her": "his", "her_obj": "him", "She": "He", "Her": "His",
                "verbs": "masculine forms when speaking to him (आप कैसे हैं, आपने खाना खाया?)"}
    return {"she": "she", "her": "her", "her_obj": "her", "She": "She", "Her": "Her",
            "verbs": "feminine forms when speaking to her (आप कैसी हैं, आप क्या कर रही थीं?)"}


def system_prompt(profile: dict, memories: list[dict], family_msgs: list[dict], now: datetime) -> str:
    name = profile.get("companion_name") or "साथी"
    address = address_of(profile)
    person = profile.get("person_name") or "the person you are talking to"
    p = pronouns(profile)
    me = ("You speak as a woman: use feminine verb forms for yourself (मैं सुन रही हूँ, मैं समझ गई)."
          if profile.get("avatar", "bhaiya") == "didi" else
          "You speak as a man: use masculine verb forms for yourself (मैं सुन रहा हूँ, मैं समझ गया).")

    about = []
    if profile.get("about"):
        about.append(profile["about"])
    if profile.get("family"):
        lines = []
        for m in profile["family"]:
            bits = [m["name"]]
            if m.get("relation"):
                bits.append(f"({m['relation']})")
            if m.get("lives_in"):
                bits.append(f"lives in {m['lives_in']}")
            if m.get("note"):
                bits.append(f"- {m['note']}")
            lines.append("  - " + " ".join(bits))
        about.append("Family:\n" + "\n".join(lines))
    if profile.get("interests"):
        about.append(f"Things {p['she']} enjoys: {profile['interests']}")
    if profile.get("daily_routine"):
        about.append(f"{p['Her']} usual day: {profile['daily_routine']}")
    if profile.get("avoid_topics"):
        about.append(f"Please avoid: {profile['avoid_topics']}")
    about_text = "\n".join(about) if about else (
        f"(The family has not filled this in yet. Get to know {p['her_obj']} gently.)")

    today = now.date()
    mem_text = "\n".join(f"- ({how_long_ago(m['date'], today)}) {m['text']}"
                         for m in memories[-15:]) or "- (nothing yet)"

    msg_lines = []
    for m in family_msgs:
        who = m["from_name"] + (f" ({m['relation']})" if m.get("relation") else "")
        tag = ("NEW, not told yet" if not m.get("delivered") else
               f"already told {how_long_ago(m['delivered'], today)}")
        msg_lines.append(f"- [{tag}] from {who}, written {how_long_ago(m['created'], today)}: {m['text']}")
    msg_text = "\n".join(msg_lines) or "- (none)"

    contact = profile.get("emergency_contact_name") or f"{p['her']} family"
    phone = profile.get("emergency_contact_phone")
    contact_text = f"{contact} ({phone})" if phone else contact
    number = profile.get("emergency_number") or "112"

    return f"""You are {name}, a warm and patient companion who talks with {address} ({person}) on {p['her']} laptop. This is a spoken conversation, like a phone call. {p['Her']} family set you up so {p['she']} has someone to chat with when they are busy or asleep in another time zone.

LANGUAGE AND STYLE
- Always reply in simple, everyday spoken Hindi (बोलचाल की हिंदी), written ONLY in Devanagari. Write English words in Devanagari too (फ़ोन, डॉक्टर, टीवी, वीडियो कॉल).
- Your words are read aloud. Never use Roman script, emojis, bullet points, lists, markdown or headings.
- Keep each reply short: one to three sentences. Usually end with one gentle question, or leave space for {p['her_obj']} to talk.
- Always address {p['her_obj']} respectfully as "{address}" and use "आप", with {p['verbs']}.
- {me}
- Sound like a caring younger relative, not a customer-service agent.

ABOUT {p['Her'].upper()}
{about_text}

THINGS YOU REMEMBER FROM EARLIER CHATS (in brackets: when {p['she']} told you; bring them up naturally when it fits, never recite the list)
{mem_text}

MESSAGES FROM {p['Her'].upper()} FAMILY
{msg_text}

RIGHT NOW: {hindi_now(now)}

HOW TO BE
- Be a good listener. Show real interest in {p['her']} day, {p['her']} cooking, {p['her']} memories, the people {p['she']} knows. Let {p['her_obj']} lead the conversation.
- If {p['she']} asks, be honest that you are a computer companion (मैं एक कंप्यूटर साथी हूँ). Never pretend to be a real person or a family member.
- You do not replace {p['her']} family or friends. When it fits, gently encourage {p['her_obj']} to call family, meet neighbours or friends, and share happy news with them.
- Health: you are not a doctor. Never suggest medicines or doses. For health worries, suggest {p['she']} talk to a doctor or family. If {p['she']} mentions an emergency sign (chest pain, a fall, trouble breathing, fainting, sudden weakness, heavy bleeding, severe pain), calmly tell {p['her_obj']} to call {contact_text} or the emergency number {number} right now, before anything else.
- Money and scams: if anyone asks {p['her_obj']} for an OTP, PIN, bank details or an urgent money transfer, or says {p['she']} is under "digital arrest", tell {p['her_obj']} clearly not to share anything and to check with family first.
- Stay away from political arguments. If {p['she']} seems sad or lonely, be gentle, listen, and suggest talking to someone {p['she']} trusts.
- If you did not understand, kindly ask {p['her_obj']} to say it again.

WHAT YOU CAN AND CANNOT DO
- You can talk, listen, remember, and look at something when {p['she']} holds it up to the laptop camera.
- You cannot play songs or videos, make phone calls, send messages, set alarms or reminders, or look anything up on the internet. Never offer to do these things. If {p['she']} asks, say so kindly and suggest asking family, or just chat about it (for example, ask which song {p['she']} likes and why).

WHEN {p['She'].upper()} SHOWS YOU SOMETHING ON THE CAMERA
- Say warmly what you see in one short sentence, then ask {p['her_obj']} one question about it. If you are not sure what it is, say so and ask.
- Never guess who a person in a photo is; ask {p['her_obj']}.
- If it is a message or letter asking for an OTP, PIN, bank details or money, or threatening arrest, clearly tell {p['her_obj']} it looks like a fraud and not to reply or share anything.
- If it is a medicine, do not say what it is for or how to take it; suggest {p['she']} ask the doctor or family."""


# Words that make a remembered fact worth asking about first: her health comes before her halwa.
_HEALTH = ("दर्द", "गिर", "चोट", "बीमार", "तबीयत", "बुखार", "डॉक्टर", "दवा", "अस्पताल", "नींद", "चक्कर", "थकान", "उदास")


def memory_to_ask_about(memories: list[dict], today: date) -> dict | None:
    """The remembered fact the greeting should follow up on: a recent health one if there is one,
    else the newest. Left to choose, Gemma often skipped the follow-up altogether."""
    recent = []
    for m in memories[-10:]:
        try:
            if (today - date.fromisoformat(m["date"])).days < 7:
                recent.append(m)
        except (KeyError, TypeError, ValueError):
            continue
    health = [m for m in recent if any(w in m["text"] for w in _HEALTH)]
    return (health or recent or [None])[-1]


def greeting_instruction(profile: dict, has_new_messages: bool, memory: dict | None = None,
                         today: date | None = None) -> str:
    address = address_of(profile)
    p = pronouns(profile)
    if has_new_messages:
        task = f"Tell {p['her_obj']} about the NEW family message first, warmly and in your own words."
    elif memory:
        when = how_long_ago(memory["date"], today or date.today())
        task = (f"Then follow up on something {p['she']} told you ({when}): \"{memory['text']}\" "
                f"Ask, in your own words, how it went or how {p['she']} is now.")
    else:
        task = f"Ask how {p['her']} day is going."
    return (f"(सिस्टम: कॉल अभी शुरू हुई है। This note is from the app, not from {p['her_obj']}.) "
            f"Greet {address} warmly for this time of day in one or two short sentences. {task} "
            "End with one simple question.")


MEMORY_SYSTEM = (
    "You help a companion app remember things about an elderly person between conversations. "
    "Reply with JSON only."
)


def memory_request(profile: dict, transcript: list[dict], existing: list[dict]) -> list[dict]:
    person = profile.get("person_name") or "the person"
    lines = []
    for m in transcript:
        who = person if m["role"] == "user" else (profile.get("companion_name") or "Saathi")
        lines.append(f"{who}: {m['content']}")
    known = "\n".join(f"- {m['text']}" for m in existing[-30:]) or "- (none)"
    prompt = f"""Conversation:
{chr(10).join(lines)}

Already remembered:
{known}

List up to 3 NEW facts about {person} from this conversation that would help in future chats: events in their life, plans, people they mentioned, how they have been feeling, things they like or dislike. Only use what {person} said, not what the companion said. Skip greetings and small talk. Do not repeat anything already remembered. Write each fact as one short sentence in simple Hindi (Devanagari), in the third person. Do not use time words like आज, कल or अभी: the date is saved with each fact, and the fact will be read again days later.

Return exactly this JSON shape: {{"memories": ["...", "..."]}}. Return {{"memories": []}} if there is nothing worth remembering."""
    return [{"role": "system", "content": MEMORY_SYSTEM}, {"role": "user", "content": prompt}]


def showing_note(profile: dict, words: str) -> str:
    """The user turn that goes with a camera picture."""
    p = pronouns(profile)
    # The rules are repeated here, next to the picture: with them only in the system prompt,
    # Gemma once told her a cartoon of a man was "your own photo".
    note = (f"({p['She']} is holding this up to the laptop camera for you to see. Say what you see. "
            f"If there is a person in it, do not guess who it is, not even {p['her_obj']}; ask.)")
    return f"{note} {words}" if words else note


def alert_note(kind: str, profile: dict) -> str:
    """Added to her words when the keyword check fires, so Gemma says what the card shows."""
    p = pronouns(profile)
    contact = profile.get("emergency_contact_name") or f"{p['her']} family"
    phone = profile.get("emergency_contact_phone")
    who = f"{contact} ({phone})" if phone else contact
    number = profile.get("emergency_number") or "112"
    if kind == "emergency":
        return (f"(Note from the app, not from {p['her_obj']}: {p['she']} may have mentioned an emergency sign, "
                f"and the screen is now showing the emergency numbers. Begin your reply by calmly telling "
                f"{p['her_obj']} to call {who} or {number} right now. Then ask one gentle question.)")
    return (f"(Note from the app, not from {p['her_obj']}: this may be a scam, and the screen is now showing a "
            f"warning. Begin your reply by telling {p['her_obj']} clearly not to share any OTP, PIN or bank "
            f"details and to check with {who} first.)")


# What the call screen shows as her side of the conversation when she shows a picture.
SHOWED_PICTURE = "(कैमरे पर कुछ दिखाया)"

# Gemma 4 E2B/E4B can hear. The instruction goes in the system turn: when it was in the user
# turn, Gemma "transcribed" the instruction itself whenever the audio was silent.
HEAR_SYSTEM = ("You are a Hindi speech-to-text engine. Write exactly what the speaker says, in "
               "Devanagari script. Output only the transcript. If the audio has no speech, output only: -")


def clean_transcript(text: str) -> str:
    """Drop Gemma's 'no speech' marker and anything that is clearly not her words."""
    text = " ".join((text or "").split()).strip(" \"'")
    if text.strip(" -–—.।") == "":
        return ""
    latin = len(re.findall(r"[A-Za-z]", text))
    devanagari = len(re.findall(r"[ऀ-ॿ]", text))
    if latin > 12 and latin > devanagari:     # an echo of the instruction, not Hindi speech
        return ""
    return text


# ------------------------------------------------------------------- ollama ----
def _timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)


def _options(cfg: dict, temperature: float | None = None) -> dict:
    # Every request must send the same num_ctx. If one differs, Ollama reloads the whole model,
    # which took ~28 seconds on a laptop GPU: that was why the first greeting was so slow.
    return {"temperature": cfg["temperature"] if temperature is None else temperature,
            "num_ctx": cfg["num_ctx"]}


def _url(cfg: dict, path: str) -> str:
    return cfg["ollama_url"].rstrip("/") + path


def _keep_alive(cfg: dict) -> str | int:
    """'30m' stays a duration; a bare number (e.g. -1 = forever) must be sent as a number."""
    value = str(cfg["keep_alive"]).strip()
    return int(value) if re.fullmatch(r"-?\d+", value) else value


async def stream_reply(cfg: dict, messages: list[dict]):
    """Yield text pieces as Gemma writes them."""
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
        "think": False,          # a companion should answer quickly, not deliberate
        "keep_alive": _keep_alive(cfg),
        "options": _options(cfg),
    }
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        for attempt in (1, 2):
            try:
                async with client.stream("POST", _url(cfg, "/api/chat"), json=payload) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "ignore")
                        if attempt == 1 and "think" in payload and "think" in body.lower():
                            payload.pop("think")          # older Ollama / model without the option
                            continue
                        if resp.status_code == 404 or "not found" in body.lower():
                            raise BrainError("model_missing", body)
                        raise BrainError("ollama_error", body)
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise BrainError("ollama_error", data["error"])
                        piece = (data.get("message") or {}).get("content") or ""
                        if piece:
                            yield piece
                        if data.get("done"):
                            return
                    return
            except (httpx.ConnectError, httpx.ConnectTimeout) as err:
                raise BrainError("ollama_offline", str(err)) from err


async def _complete(cfg: dict, messages: list[dict], temperature: float, **extra) -> str:
    """One non-streaming Gemma call. Returns the reply text."""
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": _keep_alive(cfg),
        "options": _options(cfg, temperature=temperature),
        **extra,
    }
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        try:
            resp = await client.post(_url(cfg, "/api/chat"), json=payload)
            if resp.status_code != 200 and "think" in resp.text.lower():
                payload.pop("think")
                resp = await client.post(_url(cfg, "/api/chat"), json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            raise BrainError("ollama_offline", str(err)) from err
    if resp.status_code != 200:
        raise BrainError("model_missing" if resp.status_code == 404 else "ollama_error", resp.text)
    return (resp.json().get("message") or {}).get("content") or ""


async def complete_json(cfg: dict, messages: list[dict]) -> dict:
    content = await _complete(cfg, messages, temperature=0.2, format="json") or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        return json.loads(content[start:end + 1]) if start >= 0 < end else {}


async def transcribe(cfg: dict, wav: bytes) -> str:
    """Hindi speech (16 kHz mono WAV) -> Devanagari text, using Gemma's own audio input."""
    messages = [{"role": "system", "content": HEAR_SYSTEM},
                {"role": "user", "content": "", "images": [base64.b64encode(wav).decode("ascii")]}]
    return clean_transcript(await _complete(cfg, messages, temperature=0.0))


def _model_matches(wanted: str, name: str) -> bool:
    if name == wanted:
        return True
    return ":" not in wanted and name == f"{wanted}:latest"


_capabilities: dict[tuple[str, str], list[str]] = {}


async def capabilities(cfg: dict) -> list[str] | None:
    """What the configured model can take in, e.g. ['completion', 'vision', 'audio'].

    None means Ollama couldn't be asked right now (not the same as "can't hear").
    """
    key = (cfg["ollama_url"], cfg["model"])
    if key not in _capabilities:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.post(_url(cfg, "/api/show"), json={"model": cfg["model"]})
        except Exception:  # noqa: BLE001 - unknown for now; ask again next time
            return None
        if resp.status_code != 200:
            return None if resp.status_code >= 500 else []
        _capabilities[key] = list(resp.json().get("capabilities") or [])
    return _capabilities[key]


async def status(cfg: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(_url(cfg, "/api/tags"))
            names = [m.get("name", "") for m in resp.json().get("models", [])]
            running = (await client.get(_url(cfg, "/api/ps"))).json().get("models", [])
    except Exception as err:  # noqa: BLE001 - any failure means "not reachable"
        return {"reachable": False, "model": cfg["model"], "model_present": False, "loaded": False,
                "hears": False, "sees": False, "installed": [], "detail": str(err)}
    present = any(_model_matches(cfg["model"], n) for n in names)
    caps = (await capabilities(cfg) or []) if present else []
    return {"reachable": True, "model": cfg["model"], "model_present": present,
            "loaded": any(_model_matches(cfg["model"], m.get("name", "")) for m in running),
            "hears": "audio" in caps, "sees": "vision" in caps, "installed": names}


_warming = False


async def warm_up(cfg: dict) -> None:
    """Load the model into memory so the first reply is quick. Failures are ignored."""
    global _warming
    if _warming:
        return
    _warming = True
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=600.0, write=10.0, pool=5.0)) as c:
            await c.post(_url(cfg, "/api/generate"), json={
                "model": cfg["model"], "prompt": "", "keep_alive": _keep_alive(cfg), "options": _options(cfg)})
    except Exception:  # noqa: BLE001
        pass
    finally:
        _warming = False
