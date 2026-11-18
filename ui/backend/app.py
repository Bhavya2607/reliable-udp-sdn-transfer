import asyncio
import json
import urllib.request
from pathlib import Path
from typing import Set
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = Path(__file__).parent / "uploads"
UPLOADS.mkdir(exist_ok=True)
MININET_API = "http://127.0.0.1:8765"
app = FastAPI(title="Reliable UDP + Mininet dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
clients: Set[WebSocket] = set()
state = {"receiver": "stopped", "transfer": "idle"}
last_event_id = 0


def mininet_request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(MININET_API + path, data=body,
        headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.loads(response.read())
    except Exception as exc:
        raise HTTPException(503, f"Mininet control API unavailable: {exc}")


@app.get("/api/status")
async def status():
    try:
        remote = mininet_request("/status")
        state["receiver"] = "running" if remote["receiver"] else "stopped"
        state["transfer"] = "running" if remote["transfer"] else state["transfer"]
        return {**state, "controller": {"reachable": True, "active_path": remote.get("active_path", []), "down_ports": []}, "mininet": True}
    except HTTPException:
        return {**state, "controller": {"reachable": False, "active_path": [], "down_ports": []}, "mininet": False}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    name = Path(file.filename or "upload.bin").name
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    path = UPLOADS / name
    path.write_bytes(data)
    return {"path": str(path), "name": name, "size": len(data)}


@app.post("/api/receiver/start")
async def start_receiver():
    result = mininet_request("/receiver/start", {})
    state["receiver"] = "running"
    return result


@app.post("/api/transfer/start")
async def start_transfer(data: dict):
    path = Path(data.get("path", ""))
    if not path.is_file():
        raise HTTPException(400, "Upload a file first")
    result = mininet_request("/transfer/start", {"path": str(path)})
    state["transfer"] = "running"
    return result


@app.post("/api/experiment")
async def experiment(data: dict):
    return mininet_request("/experiment", data)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    global last_event_id
    await ws.accept()
    clients.add(ws)
    cursor = 0
    try:
        while True:
            try:
                req = urllib.request.urlopen(MININET_API + f"/events?since={cursor}", timeout=1)
                batch = json.loads(req.read())
                for event in batch.get("events", []):
                    cursor = max(cursor, event["id"])
                    await ws.send_json(event)
                    if event.get("type") == "transfer_state":
                        state["transfer"] = event.get("state", state["transfer"])
                    if event.get("type") == "receiver_state":
                        state["receiver"] = event.get("state", state["receiver"])
            except Exception:
                await ws.send_json({"type": "connection", "state": "mininet_api_unavailable"})
            await asyncio.sleep(0.35)
    except WebSocketDisconnect:
        clients.discard(ws)
