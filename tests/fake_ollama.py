"""A tiny stand-in for Ollama, so the server can be tested without downloading Gemma."""
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
REQUESTS: list[dict] = []          # every /api/chat body
WARMUPS: list[dict] = []           # every /api/generate body
LOADED: set[str] = set()
REPLY = "नमस्ते मौसी जी! आज आपका दिन कैसा रहा? क्या आपने खाना खा लिया।"
HEARD = "आज मैंने खीर बनाई"


@app.get("/api/tags")
def tags():
    return {"models": [{"name": "gemma4:e4b"}, {"name": "nothink-model:latest"}]}


@app.get("/api/ps")
def ps():
    return {"models": [{"name": name} for name in LOADED]}


@app.post("/api/show")
async def show(request: Request):
    model = (await request.json())["model"]
    if model == "gemma4:e4b":
        return {"capabilities": ["completion", "vision", "audio", "tools", "thinking"]}
    return {"capabilities": ["completion"]}


@app.post("/api/generate")
async def generate(request: Request):
    body = await request.json()
    WARMUPS.append(body)
    LOADED.add(body["model"])
    return {"done": True}


def _stream(text: str):
    def gen():
        for word in text.split(" "):
            yield json.dumps({"message": {"role": "assistant", "content": word + " "}, "done": False},
                             ensure_ascii=False) + "\n"
            time.sleep(0.01)
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    REQUESTS.append(body)
    if body.get("think") is not None and body["model"].startswith("nothink-model"):
        return JSONResponse({"error": f"\"{body['model']}\" does not support thinking"}, status_code=400)
    if body["model"] == "missing-model":
        return JSONResponse({"error": "model 'missing-model' not found"}, status_code=404)
    messages = body["messages"]
    if messages[0]["role"] == "system" and "speech-to-text" in messages[0]["content"]:
        return {"message": {"role": "assistant", "content": HEARD}, "done": True}
    if body.get("format") == "json":
        return {"message": {"role": "assistant",
                            "content": json.dumps({"memories": ["मौसी जी ने आलू के पराठे बनाए।"]},
                                                  ensure_ascii=False)}, "done": True}
    return _stream(REPLY)
