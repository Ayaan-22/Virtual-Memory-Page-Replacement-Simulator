"""Local engine for the HTML visualizer:  python -m vmsim serve

GET  /api/health    -> {"ok": true, "version": ...}     (the visualizer polls this)
POST /api/simulate  -> every policy on one string       {refs:[[page,write],...], frames, tlb, prefetch}
POST /api/sweep     -> faults vs frame counts           {refs, frames:[...], tlb, prefetch, policies?}

Standard library only. Binds to 127.0.0.1 by default; inputs are size-capped.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .algorithms import POLICIES
from .experiments import frames_sweep
from .simulator import Config, simulate

MAX_BODY, MAX_REFS = 500_000, 5_000
MAX_WORK = 100_000        # policy-steps per request (refs x policies x frame counts); the CLI handles bigger jobs


def _int(body: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = int(body.get(key, default))
    if not lo <= v <= hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return v


def _refs(body: dict):
    refs = body.get("refs")
    if not isinstance(refs, list) or not 0 < len(refs) <= MAX_REFS:
        raise ValueError(f"refs must be a list of 1 to {MAX_REFS} [page, write] pairs")
    out = [(int(p), bool(w)) for p, w in refs]
    if any(p < 0 for p, _ in out):
        raise ValueError("pages must be non-negative")
    return out


def _cfg(body: dict, frames: int | None = None) -> Config:
    return Config(frames=frames if frames is not None else _int(body, "frames", 4, 1, 64),
                  tlb_size=_int(body, "tlb", 0, 0, 64), prefetch_depth=_int(body, "prefetch", 0, 0, 8))


def _budget(steps: int) -> None:
    if steps > MAX_WORK:
        raise ValueError(f"request too large ({steps:,} simulation steps, limit {MAX_WORK:,}); use the CLI for big runs")


def simulate_all(body: dict) -> dict:
    refs, cfg, out = _refs(body), _cfg(body), {}
    _budget(len(refs) * len(POLICIES))
    for name in POLICIES:
        r = simulate(refs, name, cfg)
        out[name] = {"stats": r.stats, "events": [
            {"page": e.page, "write": e.write, "kind": e.kind, "victim": e.victim,
             "victim_dirty": e.victim_dirty, "prefetched": list(e.prefetched),
             "frames": list(e.frames), "dirty": list(e.dirty)} for e in r.events]}
    return {"results": out}


def sweep(body: dict) -> dict:
    refs = _refs(body)
    frames = [int(f) for f in body.get("frames", [])]
    if not 0 < len(frames) <= 64 or any(not 1 <= f <= 64 for f in frames):
        raise ValueError("frames must be 1 to 64 values between 1 and 64")
    pols = body.get("policies") or list(POLICIES)
    if any(p not in POLICIES for p in pols):
        raise ValueError("unknown policy in policies")
    _budget(len(refs) * len(frames) * len(pols))
    return {"frames": frames, "faults": frames_sweep(refs, pols, frames, _cfg(body, frames[0]))}


class Handler(BaseHTTPRequestHandler):
    server_version = "vmsim"
    timeout = 10                           # drop connections that stall mid-request

    def log_message(self, *args):          # keep the terminal quiet; the visualizer polls often
        pass

    def _cors(self):
        for k, v in (("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                     ("Access-Control-Allow-Headers", "Content-Type"), ("Access-Control-Allow-Private-Network", "true")):
            self.send_header(k, v)

    def _send(self, code: int, obj: dict):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            self._send(200, {"ok": True, "engine": "vmsim", "version": __version__, "policies": list(POLICIES)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        route = {"/api/simulate": simulate_all, "/api/sweep": sweep}.get(self.path.split("?")[0])
        if route is None:
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 < n <= MAX_BODY:
                raise ValueError("request body missing or too large")
            body = json.loads(self.rfile.read(n))
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            self._send(200, route(body))
        except (ValueError, TypeError, KeyError) as e:
            self._send(400, {"error": str(e)})


def make_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Handler)
