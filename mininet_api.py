"""Small HTTP control plane hosted by the Mininet process.

The UI backend talks to this service; all commands run inside the live Mininet
network object, so H1/H2 processes and link experiments use the real topology.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
events = []
lock = threading.Lock()
next_event_id = 0
processes = {"receiver": None, "sender": None}


def emit(event):
    global next_event_id
    with lock:
        next_event_id += 1
        events.append({"id": next_event_id, "time": time.time(), **event})
        del events[:-500]


def read_process(proc, source):
    for raw in iter(proc.stdout.readline, ""):
        line = raw.strip()
        if not line:
            continue
        event = {"type": "log", "source": source, "message": line}
        if line.startswith("EVENT "):
            try:
                event = json.loads(line[6:])
                event["source"] = source
            except json.JSONDecodeError:
                pass
        emit(event)
    code = proc.wait()
    emit({"type": "process_exit", "source": source, "code": code})
    if source == "sender":
        emit({"type": "transfer_state", "state": "completed" if code == 0 else "failed"})


def start_api(net, host="0.0.0.0", port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/status":
                path = []
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.settimeout(.25)
                    s.sendto(b'{"event":"status"}', ("127.0.0.1", 9999))
                    path = json.loads(s.recvfrom(2048)[0]).get("active_path", [])
                    s.close()
                except OSError:
                    pass
                self.reply(200, {"mininet": True, "hosts": ["h1", "h2"],
                                 "receiver": processes["receiver"].poll() is None if processes["receiver"] else False,
                                 "transfer": processes["sender"].poll() is None if processes["sender"] else False,
                                 "active_path": path})
            elif parsed.path == "/events":
                since = int(parse_qs(parsed.query).get("since", ["0"])[0])
                with lock:
                    oldest_id = events[0]["id"] if events else since + 1
                    last_id = events[-1]["id"] if events else since
                    batch = [e for e in events if e["id"] > since]
                self.reply(200, {"events": batch, "oldest_id": oldest_id,
                                 "last_id": last_id, "gap": since < oldest_id - 1})
            else:
                self.reply(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/receiver/start":
                    old = processes["receiver"]
                    if old and old.poll() is None:
                        return self.reply(200, {"status": "already running"})
                    proc = net.get("h2").popen(
                        ["python3", str(ROOT / "server.py")],
                        stdout=-1, stderr=-2, text=True, bufsize=1)
                    processes["receiver"] = proc
                    threading.Thread(target=read_process, args=(proc, "receiver"), daemon=True).start()
                    emit({"type": "receiver_state", "state": "running"})
                    return self.reply(200, {"status": "started"})
                if self.path == "/transfer/start":
                    old = processes["sender"]
                    if old and old.poll() is None:
                        return self.reply(409, {"error": "transfer already running"})
                    file_path = Path(data.get("path", "")).resolve()
                    if not file_path.is_file():
                        return self.reply(400, {"error": "uploaded file not found on VM"})
                    if not processes["receiver"] or processes["receiver"].poll() is not None:
                        return self.reply(409, {"error": "Start the H2 receiver first"})
                    proc = net.get("h1").popen(
                        ["python3", str(ROOT / "client.py"), str(file_path), "10.0.0.2"],
                        stdout=-1, stderr=-2, text=True, bufsize=1)
                    processes["sender"] = proc
                    # Publish the new session boundary before its reader can emit
                    # transfer_started or packet events.
                    emit({"type": "transfer_reset", "state": "running"})
                    emit({"type": "transfer_state", "state": "running"})
                    threading.Thread(target=read_process, args=(proc, "sender"), daemon=True).start()
                    return self.reply(200, {"status": "started"})
                if self.path == "/experiment":
                    action = data.get("action")
                    if action == "receiver_stop":
                        proc = processes["receiver"]
                        if proc and proc.poll() is None:
                            proc.terminate()
                            emit({"type": "receiver_state", "state": "stopped"})
                        return self.reply(200, {"status": "stopped"})
                    if action == "link_down":
                        net.configLinkStatus("s1", "s2", "down")
                    elif action == "link_up":
                        net.configLinkStatus("s1", "s2", "up")
                    elif action in ("loss", "delay", "corrupt", "clear_netem"):
                        command = {
                            "loss": "tc qdisc replace dev h1-eth0 root netem loss 30%",
                            "delay": "tc qdisc replace dev h1-eth0 root netem delay 100ms",
                            "corrupt": "tc qdisc replace dev h1-eth0 root netem corrupt 2%",
                            "clear_netem": "tc qdisc del dev h1-eth0 root 2>/dev/null || true",
                        }[action]
                        h1 = net.get("h1")
                        output = h1.cmd(command)
                        qdisc = h1.cmd("tc qdisc show dev h1-eth0").strip()
                        if action != "clear_netem" and "netem" not in qdisc:
                            emit({"type": "experiment", "action": action, "status": "failed",
                                  "output": output.strip(), "qdisc": qdisc})
                            return self.reply(500, {"error": "tc netem was not installed on h1-eth0",
                                                    "output": output.strip(), "qdisc": qdisc})
                        emit({"type": "experiment", "action": action, "status": "applied",
                              "output": output.strip(), "qdisc": qdisc})
                    else:
                        return self.reply(400, {"error": "unknown experiment"})
                    return self.reply(200, {"status": "applied", "action": action})
                self.reply(404, {"error": "not found"})
            except Exception as exc:
                self.reply(500, {"error": str(exc)})

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Mininet UI control API listening on {host}:{port}", flush=True)
    return server
