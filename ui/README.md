# Reliable UDP + SDN visual experiment dashboard

The React dashboard runs in the browser on the Mac. The FastAPI backend and Mininet control API run inside the Ubuntu VM, so file uploads are stored on the VM and transfers execute in Mininet namespaces H1 and H2.

## Ubuntu VM (backend + Mininet)

Keep OS-Ken running in its own terminal:
```bash
cd ~/reliable-udp-sdn-transfer
source .venv/bin/activate
osken-manager controller.py --ofp-tcp-listen-port 6653
```

Stop the currently running Mininet CLI with `exit` (or Ctrl+C), update the feature branch, then start the topology again:
```bash
cd ~/reliable-udp-sdn-transfer
git pull origin feature/visual-transfer-ui
sudo python3 topology.py
```

The topology starts a small control API on port 8765 automatically. In another Ubuntu terminal, start the dashboard backend:
```bash
cd ~/reliable-udp-sdn-transfer/ui/backend
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Find the Ubuntu VM IP:
```bash
hostname -I
```

Allow inbound TCP ports 8000 (dashboard API) and 8765 (Mininet control API, local to the VM only). Only port 8000 needs to be reachable from the Mac. Do not expose port 8765 to untrusted networks.

## Mac (frontend)

In the Mac terminal, inside your local repository's `ui/frontend`:
```bash
npm install
VITE_API_URL=http://UBUNTU_VM_IP:8000 npm run dev -- --host 0.0.0.0
```

Replace `UBUNTU_VM_IP` with the address returned by `hostname -I` in Ubuntu. Open the Vite URL on the Mac, usually http://localhost:5173. If the VM IP changes, update `VITE_API_URL` and restart Vite.

## What the dashboard controls

- File upload is sent to the Ubuntu backend and saved on the VM.
- Start receiver launches `server.py` inside Mininet H2.
- Send file launches `client.py` inside Mininet H1, targeting 10.0.0.2:5001.
- Structured DATA, ACK, retransmission and integrity events are streamed from the real H1/H2 processes.
- Topology path is read from the OS-Ken telemetry listener.
- Experiment buttons directly apply link down/up and netem loss, delay, corruption, and reset actions to the live Mininet network.

The four-switch Mininet diamond is H1-S1-(S2/S3)-S4-H2. The UI does not claim that Mininet controls the Mac's physical Wi-Fi/Ethernet path; it visualizes and controls the isolated SDN lab topology.
