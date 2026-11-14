"""Minimal ASGI app (no web framework): JSON API + static frontend.

Run:  uvicorn backend.api.server:app --port 8000
Environment: LUNAR_DEM=/path/to/dem.npz  LUNAR_SITES=/path/to/sites.json
             ANTHROPIC_API_KEY=...  (optional: enables the LLM paths of the agents)
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path

import numpy as np

from ..orchestrator import run_copilot
from ..service import Service, ServiceError

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
MAX_BODY = 1_000_000
_svc: Service | None = None


def get_service() -> Service:
    global _svc
    if _svc is None:
        _svc = Service()
    return _svc


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, np.datetime64):
        return str(o)
    raise TypeError(f"not JSON serializable: {type(o)}")


# ------------------------------------------------------------------ handlers
def h_meta(svc, body):
    return svc.meta()


def h_series(svc, b):
    return svc.series_payload(b["site_ids"], b["start"], b["end"], float(b.get("step_h", 1.0)),
                              float(b.get("height_m", 0.0)))


def h_windows(svc, b):
    return svc.windows(b["site_id"], b["start"], b["end"], float(b["duration_h"]),
                       b.get("objective", "balanced"),
                       None if b.get("battery_h") in (None, "") else float(b["battery_h"]),
                       float(b.get("height_m", 0.0)), float(b.get("step_h", 1.0)),
                       int(b.get("top_n", 3)), bool(b.get("uncertainty", True)))


def h_window_prob(svc, b):
    return svc.window_probability(
        b["site_id"], b["start"], b["end"], float(b["duration_h"]), int(b.get("rank", 0)),
        objective=b.get("objective", "balanced"),
        battery_h=None if b.get("battery_h") in (None, "") else float(b["battery_h"]),
        height_m=float(b.get("height_m", 0.0)), step_h=float(b.get("step_h", 1.0)))


def h_height(svc, b):
    return svc.height(b["site_id"], b["start"], b["end"], b.get("heights"),
                      b.get("window_start"), b.get("window_end"), float(b.get("step_h", 1.0)))


def h_copilot(svc, b):
    msg = str(b.get("message", "")).strip()
    if not msg:
        raise ServiceError("type a question first")
    if len(msg) > 1000:
        raise ServiceError("question too long (max 1000 characters)")
    mode = b.get("mode") if b.get("mode") in ("planner", "public") else "planner"
    return run_copilot(svc, msg, mode)


ROUTES = {
    ("GET", "/api/meta"): h_meta,
    ("POST", "/api/series"): h_series,
    ("POST", "/api/windows"): h_windows,
    ("POST", "/api/window_probability"): h_window_prob,
    ("POST", "/api/height"): h_height,
    ("POST", "/api/copilot"): h_copilot,
}


# ---------------------------------------------------------------------- ASGI
async def _send(send, status, body: bytes, ctype="application/json"):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", ctype.encode()), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


async def _json(send, status, obj):
    await _send(send, status, json.dumps(obj, default=_json_default).encode())


async def _read_body(receive) -> bytes:
    chunks, size = [], 0
    while True:
        msg = await receive()
        chunk = msg.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            raise ServiceError("request body too large")
        chunks.append(chunk)
        if not msg.get("more_body"):
            return b"".join(chunks)


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            m = await receive()
            if m["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif m["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return
    method, path = scope["method"], scope["path"]

    handler = ROUTES.get((method, path))
    if handler:
        try:
            raw = await _read_body(receive) if method == "POST" else b""
            body = json.loads(raw) if raw else {}
            result = await asyncio.to_thread(handler, get_service(), body)
            await _json(send, 200, result)
        except (ServiceError, KeyError, ValueError, json.JSONDecodeError) as exc:
            msg = f"missing field {exc}" if isinstance(exc, KeyError) else str(exc)
            await _json(send, 400, {"error": msg})
        except Exception:  # noqa: BLE001
            await _json(send, 500, {"error": "internal error"})
        return

    if method == "GET":
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        target = (FRONTEND / rel).resolve()
        if FRONTEND.resolve() in target.parents and target.is_file():
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            await _send(send, 200, target.read_bytes(), ctype)
            return
    await _json(send, 404, {"error": "not found"})
