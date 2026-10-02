"""Saathi's brain: builds the prompt and talks to Gemma through a local Ollama server.

Nothing here calls the internet. Ollama runs on the same laptop (http://127.0.0.1:11434).
"""
import json
from datetime import datetime

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

    mem_text = "\n".join(f"- ({m['date']}) {m['text']}" for m in memories[-15:]) or "- (nothing yet)"

    msg_lines = []
    for m in family_msgs:
        who = m["from_name"] + (f" ({m['relation']})" if m.get("relation") else "")
        tag = "NEW, not told yet" if not m.get("delivered") else f"already told on {m['delivered']}"
        msg_lines.append(f"- [{tag}] from {who}, written {m['created']}: {m['text']}")
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

THINGS YOU REMEMBER FROM EARLIER CHATS (bring them up naturally when it fits; never recite the list)
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
- If you did not understand, kindly ask {p['her_obj']} to say it again."""


def greeting_instruction(profile: dict, has_new_messages: bool) -> str:
    address = address_of(profile)
    p = pronouns(profile)
    task = (f"Tell {p['her_obj']} about the NEW family message first, warmly and in your own words."
            if has_new_messages else
            f"If you remember something from earlier chats, ask about it. Otherwise ask how {p['her']} day is going.")
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

List up to 3 NEW facts about {person} from this conversation that would help in future chats: events in their life, plans, people they mentioned, how they have been feeling, things they like or dislike. Only use what {person} said, not what the companion said. Skip greetings and small talk. Do not repeat anything already remembered. Write each fact as one short sentence in simple Hindi (Devanagari), in the third person.

Return exactly this JSON shape: {{"memories": ["...", "..."]}}. Return {{"memories": []}} if there is nothing worth remembering."""
    return [{"role": "system", "content": MEMORY_SYSTEM}, {"role": "user", "content": prompt}]


# ------------------------------------------------------------------- ollama ----
def _timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0)


def _options(cfg: dict, temperature: float | None = None) -> dict:
    return {"temperature": cfg["temperature"] if temperature is None else temperature,
            "num_ctx": cfg["num_ctx"]}


async def stream_reply(cfg: dict, messages: list[dict]):
    """Yield text pieces as Gemma writes them."""
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
        "think": False,          # a companion should answer quickly, not deliberate
        "keep_alive": "2h",      # keep the model in memory between calls
        "options": _options(cfg),
    }
    url = cfg["ollama_url"].rstrip("/") + "/api/chat"
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        for attempt in (1, 2):
            try:
                async with client.stream("POST", url, json=payload) as resp:
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


async def complete_json(cfg: dict, messages: list[dict]) -> dict:
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "2h",
        "options": _options(cfg, temperature=0.2),
    }
    url = cfg["ollama_url"].rstrip("/") + "/api/chat"
    async with httpx.AsyncClient(timeout=_timeout()) as client:
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200 and "think" in resp.text.lower():
                payload.pop("think")
                resp = await client.post(url, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            raise BrainError("ollama_offline", str(err)) from err
    if resp.status_code != 200:
        raise BrainError("ollama_error", resp.text)
    content = (resp.json().get("message") or {}).get("content") or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        return json.loads(content[start:end + 1]) if start >= 0 < end else {}


def _model_matches(wanted: str, name: str) -> bool:
    if name == wanted:
        return True
    return ":" not in wanted and name == f"{wanted}:latest"


async def status(cfg: dict) -> dict:
    url = cfg["ollama_url"].rstrip("/") + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(url)
        names = [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception as err:  # noqa: BLE001 - any failure means "not reachable"
        return {"reachable": False, "model": cfg["model"], "model_present": False,
                "installed": [], "detail": str(err)}
    return {"reachable": True, "model": cfg["model"],
            "model_present": any(_model_matches(cfg["model"], n) for n in names),
            "installed": names}


async def warm_up(cfg: dict) -> None:
    """Load the model into memory so the first reply is quick. Failures are ignored."""
    url = cfg["ollama_url"].rstrip("/") + "/api/generate"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=600.0, write=10.0, pool=5.0)) as c:
            await c.post(url, json={"model": cfg["model"], "prompt": "", "keep_alive": "2h"})
    except Exception:  # noqa: BLE001
        pass
