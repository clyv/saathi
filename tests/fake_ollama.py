"""A tiny stand-in for Ollama, so the server can be tested without downloading Gemma."""
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
REQUESTS: list[dict] = []
REPLY = "नमस्ते मौसी जी! आज आपका दिन कैसा रहा? क्या आपने खाना खा लिया।"


@app.get("/api/tags")
def tags():
    return {"models": [{"name": "gemma4:e4b"}, {"name": "nothink-model:latest"}]}


@app.post("/api/generate")
async def generate(request: Request):
    return {"done": True}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    REQUESTS.append(body)
    if body.get("think") is not None and body["model"].startswith("nothink-model"):
        return JSONResponse({"error": f"\"{body['model']}\" does not support thinking"}, status_code=400)
    if body["model"] == "missing-model":
        return JSONResponse({"error": "model 'missing-model' not found"}, status_code=404)
    if body.get("format") == "json":
        return {"message": {"role": "assistant",
                            "content": json.dumps({"memories": ["मौसी जी ने आज आलू के पराठे बनाए।"]},
                                                  ensure_ascii=False)}, "done": True}

    def stream():
        for word in REPLY.split(" "):
            yield json.dumps({"message": {"role": "assistant", "content": word + " "}, "done": False},
                             ensure_ascii=False) + "\n"
            time.sleep(0.01)
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")
