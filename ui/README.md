# Reliable UDP + SDN visual experiment dashboard

The UI is a simple React/Vite dashboard with a FastAPI bridge around the existing UDP sender and receiver.

## Run locally

Backend terminal:
```bash
cd ui/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Frontend terminal:
```bash
cd ui/frontend
npm install
npm run dev
```

Open http://localhost:5173. Upload a file, start the local receiver, then send to 127.0.0.1.

## Dashboard sections

1. Four-switch Mininet diamond: H1-S1-(S2/S3)-S4-H2. The route highlight is based on the controller's reported path.
2. File transfer: launches the existing client.py and server.py for localhost testing.
3. Live progress: DATA sends, cumulative ACKs, retransmissions and acknowledged packet count.
4. Sliding window: sequence numbers and waiting/sent/retransmitted/acknowledged states.
5. Experiments: copy commands for link down/up, netem packet loss, delay, corruption and receiver stop/restart.
6. Event log: structured sender and receiver events streamed through WebSocket.

## Experiments

Run the displayed commands in the Mininet CLI inside the Ubuntu VM after starting the controller and topology. The browser does not execute Mininet commands: the UI runs on the host while Mininet is isolated in the VM. Each experiment includes a recovery command.

## Network modes and limitations

- Localhost mode starts both UDP processes from the FastAPI backend.
- For two physical computers, run `python3 server.py` on the receiving computer, allow inbound UDP/5001, and enter its reachable LAN IP. The current dashboard's local receiver button starts a receiver on the backend host.
- Mininet/OS-Ken is a separate virtual SDN experiment; it does not control the physical Wi-Fi/Ethernet route.
- DATA and ACK animations are triggered by structured events printed by the actual sender and receiver. The sequence numbers and retransmission counts come from those processes, not random demo data.
- Controller route highlighting is live only when the controller's UDP/9999 status listener can be reached from the backend host.
