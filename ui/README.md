# Visual transfer UI

React/Vite dashboard plus FastAPI bridge for launching the existing UDP client and receiver.

## Run
Backend terminal:
```bash
cd ui/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```
Frontend terminal:
```bash
cd ui/frontend
npm install
npm run dev
```
Open http://localhost:5173, upload a file, start the local receiver, then send to 127.0.0.1.

## Important boundaries
- The UI starts the real project server.py and client.py processes; it does not replace the protocol.
- For a second computer, run server.py on the receiving computer, allow inbound UDP/5001, and enter its reachable LAN IP in the UI.
- The Mininet/OS-Ken diamond is a separate Linux experiment. The controller panel reads its existing UDP/9999 status response only when that controller is reachable on the backend host.
- Packet-level DATA/ACK telemetry is not yet emitted by the existing client/server, so the event panel currently shows actual process output rather than fabricated per-packet animations. That instrumentation is a follow-up integration task.