"""SARP-Agent counsellor assistant: case workspace at / and team overview at /team.

Run from the repository root (Ollama should be running for AI replies):
    .venv/Scripts/python.exe -m agent.server          then open http://127.0.0.1:8000
Online, Vercel loads `app` from this file (see pyproject.toml and agent/DEPLOY.md).

Settings (environment variables):
    SARP_LLM_BASE_URL, SARP_LLM_API_KEY, SARP_LLM_MODEL    AI model (default local Ollama, gemma3:4b)
    SARP_LLM_FALLBACK_BASE_URL, _API_KEY, _MODEL           optional backup AI (see agent/llm.py)
    DATABASE_URL          Postgres for online use; without it cases go to ../agent_data/sarp_agent.db
    SARP_COUNSELLOR_PIN   PIN for the whole app (required online; optional on the PC)
    SARP_POLITICAL_PHASE  phase used for SARP-Net predictions (default Newly Elected)
    SARP_BDT_PER_USD      taka per US dollar for budgets (default 122)
    SARP_DATA_DIR         folder with splits/ for past cases and examples (default ../data)
    SARP_RATE_BROWSER_10MIN / _DAY, SARP_RATE_IP_10MIN / _DAY   message limits (0 turns a limit off)
    SARP_HOST, SARP_PORT  where to serve on the PC (default 127.0.0.1:8000)
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in (None, ""):  # started as a script (python agent/server.py): make `agent` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.chat import ChatEngine, Turn

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
WEB_DIR = Path(__file__).resolve().parent / "web"
_engine: ChatEngine | None = None
_lock = threading.Lock()
# (setting, default, window in seconds, counted per) — protects the free AI quota from abuse.
RATE_LIMITS = [
    ("SARP_RATE_BROWSER_10MIN", 40, 600, "browser"),
    ("SARP_RATE_BROWSER_DAY", 400, 86_400, "browser"),
    ("SARP_RATE_IP_10MIN", 120, 600, "ip"),
    ("SARP_RATE_IP_DAY", 1200, 86_400, "ip"),
]


def on_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def engine() -> ChatEngine:
    global _engine
    with _lock:
        if _engine is None:
            _engine = ChatEngine()
    return _engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    eng = engine()  # load SARP-Net, the case rules and past cases before the first counsellor arrives
    if not on_vercel() and eng.llm.available(max_age=0):  # online, skip checks to keep cold starts short
        threading.Thread(target=eng.llm.warm_up, daemon=True).start()
    yield


app = FastAPI(title="SARP-Agent", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


# ---------------------------------------------------------------------- pages
@app.get("/", include_in_schema=False)
def workspace_page():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/team", include_in_schema=False)
def team_page():
    return FileResponse(WEB_DIR / "counsellor.html")


@app.get("/counsellor", include_in_schema=False)
def old_team_link():
    return RedirectResponse("/team")


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------------- access
def require_pin(x_counsellor_pin: str | None = Header(default=None)) -> None:
    """The whole app is for agency staff: online it always needs the counsellor PIN."""
    expected = os.environ.get("SARP_COUNSELLOR_PIN", "")
    if not expected:
        if on_vercel():  # never serve case data publicly without a PIN
            raise HTTPException(503, "The app is turned off until SARP_COUNSELLOR_PIN is set")
        return
    if not hmac.compare_digest((x_counsellor_pin or "").encode(), expected.encode()):
        raise HTTPException(401, "Counsellor PIN required")


api = APIRouter(prefix="/api", dependencies=[Depends(require_pin)])


class ChatIn(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    text: str = Field(min_length=1, max_length=6000)
    conversation_id: str | None = Field(default=None, max_length=32)
    quick_reply: dict | None = None
    language: str | None = Field(default=None, max_length=16)
    mode: str = Field(default="case", max_length=16)


class NewConversationIn(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class FeedbackIn(BaseModel):
    client_id: str
    value: int = Field(ge=-1, le=1)


class ProfileIn(BaseModel):
    changes: dict = Field(default_factory=dict)
    dismiss: list[str] = Field(default_factory=list)
    restore: list[str] = Field(default_factory=list)


class FlagIn(BaseModel):
    flagged: bool
    note: str | None = Field(default=None, max_length=500)


def _owned(conversation_id: str, client_id: str) -> dict:
    conv = engine().store.get_conversation(conversation_id)
    if conv is None or conv["client_id"] != client_id:
        raise HTTPException(404, "Case not found")
    return conv


@api.get("/status")
def status():
    return engine().status()


@api.get("/conversations")
def list_conversations(client_id: str):
    return [{"id": c["id"], "title": c["title"] or "New case", "updated": c["updated"],
             "verdict": (c["state"] or {}).get("verdict"), "flagged": bool((c["state"] or {}).get("flag"))}
            for c in engine().store.list_conversations(client_id) if c["message_count"]]


@api.post("/conversations")
def create_conversation(body: NewConversationIn):
    return {"id": engine().store.create_conversation(body.client_id)["id"]}


@api.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, client_id: str):
    eng = engine()
    conv = _owned(conversation_id, client_id)
    messages = [{"id": m["id"], "role": m["role"], "content": m["content"], "feedback": m["feedback"],
                 "chips": m["meta"].get("chips", []) if m["role"] == "assistant" else []}
                for m in eng.store.messages(conversation_id) if m["content"]]
    state = conv["state"] or {}
    return {"id": conv["id"], "title": conv["title"] or "New case", "messages": messages,
            "language": state.get("language"), "case": eng.case_sheet(state)}


@api.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, client_id: str, body: RenameIn):
    _owned(conversation_id, client_id)
    engine().store.update_conversation(conversation_id, title=body.title.strip())
    return {"ok": True}


@api.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, client_id: str):
    _owned(conversation_id, client_id)
    engine().store.delete_conversation(conversation_id)
    return {"ok": True}


@api.post("/conversations/{conversation_id}/profile")
def update_profile(conversation_id: str, client_id: str, body: ProfileIn):
    _owned(conversation_id, client_id)
    return engine().update_profile(conversation_id, body.changes, body.dismiss, body.restore)


@api.post("/conversations/{conversation_id}/flag")
def flag_case(conversation_id: str, client_id: str, body: FlagIn):
    _owned(conversation_id, client_id)
    return engine().set_flag(conversation_id, body.flagged, body.note)


@api.post("/messages/{message_id}/feedback")
def feedback(message_id: int, body: FeedbackIn):
    owner = engine().store.message_owner(message_id)
    if owner is None or owner[1] != body.client_id:
        raise HTTPException(404, "Message not found")
    engine().store.set_feedback(message_id, body.value)
    return {"ok": True}


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or request.headers.get("x-real-ip") or (request.client.host if request.client else None)


def rate_limited(client_id: str, ip: str | None) -> bool:
    store, now = engine().store, time.time()
    for setting, default, window, per in RATE_LIMITS:
        limit = int(os.environ.get(setting, default))
        if limit <= 0 or (per == "ip" and not ip):
            continue
        count = store.count_user_messages(now - window, client_id=client_id) if per == "browser" \
            else store.count_user_messages(now - window, client_ip=ip)
        if count >= limit:
            return True
    return False


@api.post("/chat")
def chat(body: ChatIn, request: Request):
    ip = client_ip(request)
    if rate_limited(body.client_id, ip):
        return JSONResponse({"detail": "rate_limited"}, status_code=429, headers={"Retry-After": "600"})
    turn = Turn(client_id=body.client_id, text=body.text, conversation_id=body.conversation_id,
                quick_reply=body.quick_reply, language=body.language, client_ip=ip, mode=body.mode)

    def events():
        try:
            for event in engine().handle(turn):
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as error:  # surface the failure to the page instead of a silent stop
            logging.getLogger("sarp.server").exception("chat failed")
            payload = {"type": "error", "text": f"Something went wrong on the server ({type(error).__name__})."}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------- team overview (senior counsellors)
@api.get("/counsellor/conversations")
def team_list():
    eng = engine()
    return {"status": eng.detailed_status(), "political_phase": eng.tool.political_phase,
            "model_card": eng.tool.findings.model_card(),
            "conversations": [eng.counsellor_summary(c) for c in eng.store.list_conversations() if c["message_count"]]}


@api.get("/counsellor/conversations/{conversation_id}")
def team_detail(conversation_id: str):
    eng = engine()
    conv = eng.store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(404, "Case not found")
    state = conv["state"] or {}
    messages = [{"id": m["id"], "role": m["role"], "content": m["content"], "feedback": m["feedback"],
                 "created": m["created"]} for m in eng.store.messages(conversation_id) if m["content"]]
    return {"id": conv["id"], "title": conv["title"] or "New case", "updated": conv["updated"],
            "language": state.get("language"), "profile": state.get("profile", {}),
            "case": eng.case_sheet(state), "assessment": state.get("assessment"),
            "flag": state.get("flag"), "messages": messages}


app.include_router(api)


def main() -> None:
    import uvicorn

    host = os.environ.get("SARP_HOST", "127.0.0.1")
    port = int(os.environ.get("SARP_PORT", "8000"))
    print(f"SARP-Agent counsellor assistant: http://{host}:{port}  (team overview: http://{host}:{port}/team)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
