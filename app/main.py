"""Plentli web app: the API, the live event stream, and the screens."""
import asyncio
import base64
import json
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, clock, config, events, photos, tools
from .store import seed, store

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Plentli", description="Agentic food rescue for Dubai kitchens")
app.mount("/static", StaticFiles(directory=WEB), name="static")


_next_rescue = [1042]  # rescue ids read PL-1042, PL-1043, ... (reset on every demo reset)


def reset_demo() -> None:
    _next_rescue[0] = 1042
    store.clear()
    events.clear()
    photos.clear()
    clock.reset()
    seed()
    events.emit("reset", None, ["all"])


reset_demo()


def _page(name: str):
    return FileResponse(WEB / f"{name}.html", headers={"Cache-Control": "no-store"})


@app.get("/")
def home():
    return _page("index")


@app.get("/kitchen")
def kitchen_page():
    return _page("kitchen")


@app.get("/coordinator")
def coordinator_page():
    return _page("coordinator")


@app.get("/driver")
def driver_page():
    return _page("driver")


@app.get("/ops")
def ops_page():
    return _page("ops")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def get_config():
    return {
        "agent_mode": config.AGENT_MODE,
        "model": config.BEDROCK_MODEL_ID if config.AGENT_MODE == "bedrock" else "mock planner",
        "store": config.STORE,
        "routing": config.ROUTING,
        "notify": config.NOTIFY,
        "demo_clock": config.DEMO_CLOCK,
        "now": clock.fmt(clock.now()),
        "public_base_url": config.PUBLIC_BASE_URL,
        "tools": tools.TOOL_NAMES,
    }


@app.get("/api/state")
def get_state():
    rescues = sorted(store.list("rescue"), key=lambda r: r["created_ts"])
    return {
        "now": clock.fmt(clock.now()),
        "donors": store.list("donor"),
        "recipients": store.list("recipient"),
        "drivers": store.list("driver"),
        "rescues": [tools.public_rescue(r) for r in rescues],
        "offers": store.list("offer"),
        "jobs": store.list("job"),
        "last_event_id": events.latest_id(),
    }


@app.post("/api/kitchen/message")
async def kitchen_message(donor_id: str = Form("k1"), text: str = Form(""), photo: UploadFile | None = File(None)):
    donor = store.get("donor", donor_id)
    if not donor:
        raise HTTPException(404, "unknown donor")
    data = await photo.read() if photo and photo.filename else b""
    if not text.strip() and not data:
        raise HTTPException(400, "send a note, a photo, or both")

    waiting = [r for r in store.list("rescue", donor_id=donor_id) if r["status"] == "waiting_donor"]
    photo_url = None
    if waiting:
        rescue = waiting[-1]
        store.update("rescue", rescue["id"], replies=rescue.get("replies", []) + [text])
        rescue_id = rescue["id"]
    else:
        rescue_id = f"PL-{_next_rescue[0]}"
        _next_rescue[0] += 1
        store.put("rescue", {
            "id": rescue_id, "donor_id": donor_id, "note": text, "replies": [], "status": "received",
            "created_at": clock.now().isoformat(), "created_ts": time.time(), "tool_calls": 0,
            "accepted": {}, "declined": [], "offers": [], "dietary": {},
        })
        if data:
            photos.save(rescue_id, data, photo.content_type or "image/jpeg")
    if data:
        photo_url = f"/api/photo/{rescue_id}"
    events.emit("message", rescue_id, [f"kitchen:{donor_id}"], sender="kitchen", texts={"en": text, "ar": text}, photo_url=photo_url)
    if not waiting:
        events.trace(rescue_id, "intake", "CODE", f"New surplus report from {donor['name']} ({donor['contact']}): \"{text}\""
                     + (" + photo" if data else ""), {"photo_url": photo_url})
        agent.start(rescue_id)
    return {"rescue_id": rescue_id, "reply_to_question": bool(waiting)}


@app.get("/api/qr.svg")
def qr(url: str):
    """QR code (SVG) for the judge's phone, generated locally so the demo needs no QR service."""
    import io

    import qrcode
    import qrcode.image.svg

    if not url.startswith(("http://", "https://")) or len(url) > 300:
        raise HTTPException(400, "url must be an http(s) address")
    buf = io.BytesIO()
    qrcode.make(url, image_factory=qrcode.image.svg.SvgPathFillImage, border=2).save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/api/photo/{rescue_id}")
def get_photo(rescue_id: str):
    photo = photos.get(rescue_id)
    if not photo:
        raise HTTPException(404)
    return Response(base64.b64decode(photo["b64"]), media_type=photo["content_type"])


class OfferResponse(BaseModel):
    decision: str  # "accept" or "decline"


@app.post("/api/offers/{offer_id}/respond")
def respond_offer(offer_id: str, body: OfferResponse):
    if body.decision not in ("accept", "decline"):
        raise HTTPException(400, "decision must be accept or decline")
    result = tools.respond_to_offer(offer_id, body.decision)
    if not result["ok"]:
        raise HTTPException(409, result["reason"])
    return result


class StopAction(BaseModel):
    rescue_id: str
    stop_id: str = ""
    action: str  # "picked_up", "delivered", "received"


@app.post("/api/stops")
def stop_action(body: StopAction):
    if body.action not in ("picked_up", "delivered", "received"):
        raise HTTPException(400, "unknown action")
    result = tools.mark_stop(body.rescue_id, body.stop_id, body.action)
    if not result["ok"]:
        raise HTTPException(409, result["reason"])
    return result


@app.post("/api/reset")
def reset():
    reset_demo()
    return {"ok": True, "now": clock.fmt(clock.now())}


@app.get("/api/events")
async def stream(viewer: str = "ops", since: int = 0, last_event_id: str | None = Header(None)):
    """Server-sent events. viewer: ops | kitchen:<id> | recipient:<id> | driver:<id>.
    On an automatic reconnect the browser sends Last-Event-ID, so nothing is replayed twice."""
    if last_event_id and last_event_id.isdigit():
        since = int(last_event_id)

    async def gen():
        last, last_ping = since, time.time()
        yield "retry: 2000\n\n"
        while True:
            if events.latest_id() < last:  # the demo was reset
                last = 0
            batch, last = events.since(last, viewer)
            for e in batch:
                yield f"id: {e['id']}\ndata: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
            if time.time() - last_ping > 15:
                last_ping = time.time()
                yield ": ping\n\n"
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
