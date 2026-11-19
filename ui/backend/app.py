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
        if remote["transfer"]:
            state["transfer"] = "running"
        elif state["transfer"] == "running":
            # The sender process has exited; do not leave the UI's Send button disabled
            # if a WebSocket completion event was missed.
            state["transfer"] = "idle"
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


@app.get("/api/events")
async def transfer_events():
    try:
        batch = await asyncio.to_thread(mininet_request, "/events?since=0")
        items = batch.get("events", [])
        starts = [i for i, event in enumerate(items) if event.get("type") == "transfer_started"]
        if starts:
            items = items[starts[-1]:]
        return {"events": items, "gap": batch.get("gap", False)}
    except HTTPException:
        raise


@app.post("/api/experiment")
async def experiment(data: dict):
    return mininet_request("/experiment", data)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        try:
            cursor = max(0, int(ws.query_params.get("since", "0")))
        except ValueError:
            cursor = 0
        while True:
            try:
                # Keep blocking urllib I/O off the asyncio event loop so status,
                # uploads and other WebSocket work remain responsive.
                batch = await asyncio.to_thread(mininet_request, f"/events?since={cursor}")
                if batch.get("gap"):
                    await ws.send_json({"type": "event_gap", "oldest_id": batch.get("oldest_id"),
                                        "last_id": batch.get("last_id")})
                for event in batch.get("events", []):
                    cursor = max(cursor, int(event["id"]))
                    await ws.send_json(event)
                    if event.get("type") == "transfer_state":
                        state["transfer"] = event.get("state", state["transfer"])
                    elif event.get("type") == "receiver_state":
                        state["receiver"] = event.get("state", state["receiver"])
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                await ws.send_json({"type": "connection", "state": "mininet_api_unavailable",
                                    "message": str(exc)})
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass
