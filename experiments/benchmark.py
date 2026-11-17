#!/usr/bin/env python3
"""Repeatable localhost benchmark: stop-and-wait UDP baseline vs reliable windowed UDP.

This isolates transport overhead. It is NOT a substitute for Mininet static-vs-failover
measurements; those are documented in experiments/mininet_failover.md.
"""
import argparse, csv, hashlib, os, socket, subprocess, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from protocol import CHUNK_SIZE, encode, decode, DATA, ACK


def baseline_once(data, port):
    ready = threading.Event()
    received = bytearray()
    def receiver():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(('127.0.0.1', port)); ready.set()
        expected = 0
        while len(received) < len(data):
            pkt, addr = s.recvfrom(4096)
            seq = int.from_bytes(pkt[:4], 'big'); payload = pkt[4:]
            if seq == expected:
                received.extend(payload); expected += 1
            s.sendto(expected.to_bytes(4, 'big'), addr)
        s.close()
    th = threading.Thread(target=receiver, daemon=True); th.start(); ready.wait()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(2)
    started = time.perf_counter()
    for seq, off in enumerate(range(0, len(data), CHUNK_SIZE)):
        payload = seq.to_bytes(4, 'big') + data[off:off+CHUNK_SIZE]
        while True:
            s.sendto(payload, ('127.0.0.1', port))
            ack, _ = s.recvfrom(32)
            if int.from_bytes(ack, 'big') >= seq + 1: break
    elapsed = time.perf_counter() - started; s.close(); th.join(2)
    if bytes(received) != data: raise RuntimeError('baseline integrity failure')
    return elapsed


def reliable_once(data, port, trial):
    with tempfile.TemporaryDirectory() as td:
        src = Path(td)/'payload.bin'; src.write_bytes(data)
        server = subprocess.Popen([sys.executable, str(ROOT/'server.py'), '--host', '127.0.0.1', '--port', str(port), '--output', td], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(.25)
            t0 = time.perf_counter()
            run = subprocess.run([sys.executable, str(ROOT/'client.py'), str(src), '127.0.0.1', '--port', str(port)], cwd=ROOT, capture_output=True, text=True, timeout=60)
            if run.returncode: raise RuntimeError(run.stderr + run.stdout)
            # Use the client's protocol timer (starts after READY), excluding Python startup.
            elapsed = next(float(line.split(':', 1)[1].strip()) for line in run.stdout.splitlines() if line.startswith('Elapsed seconds:'))
            dst = Path(td)/'received_files'/'payload.bin'
            # server output defaults overridden to td; server writes td/payload.bin
            dst = Path(td)/'payload.bin'
            if not dst.exists() or hashlib.sha256(dst.read_bytes()).digest() != hashlib.sha256(data).digest():
                raise RuntimeError('reliable transfer integrity failure')
            retrans = 0
            for line in run.stdout.splitlines():
                if 'retransmissions:' in line:
                    retrans = int(line.split('retransmissions:')[-1].strip())
            return elapsed, retrans
        finally:
            server.terminate(); server.wait(timeout=5)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--size-mib', type=int, default=2); ap.add_argument('--trials', type=int, default=3); ap.add_argument('--port', type=int, default=18501); ap.add_argument('--out', default='evidence/benchmark.csv'); args=ap.parse_args()
    data=os.urandom(args.size_mib*1024*1024); rows=[]
    for trial in range(1,args.trials+1):
        bp=args.port + trial*2
        b=baseline_once(data,bp)
        r,retries=reliable_once(data,bp+1,trial)
        rows += [{'trial':trial,'mode':'stop_and_wait_baseline','size_bytes':len(data),'seconds':round(b,6),'mbps':round(len(data)*8/b/1e6,4),'retransmissions':'n/a','sha256':hashlib.sha256(data).hexdigest()},
                 {'trial':trial,'mode':'reliable_udp_windowed','size_bytes':len(data),'seconds':round(r,6),'mbps':round(len(data)*8/r/1e6,4),'retransmissions':retries,'sha256':hashlib.sha256(data).hexdigest()}]
        print(f'trial {trial}: baseline={b:.3f}s reliable={r:.3f}s retransmissions={retries}')
    out=ROOT/args.out; out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    print('Wrote',out)
    try:
        import matplotlib.pyplot as plt
        labels=['Stop-and-wait baseline','Reliable UDP (windowed)']
        means=[sum(x['mbps'] for x in rows if x['mode']==m)/args.trials for m in ('stop_and_wait_baseline','reliable_udp_windowed')]
        fig,ax=plt.subplots(); ax.bar(labels,means); ax.set_ylabel('Throughput (Mbps)'); ax.set_title('Localhost transport benchmark'); ax.tick_params(axis='x',rotation=10); fig.tight_layout()
        fig.savefig(ROOT/'evidence'/'benchmark.png',dpi=160); plt.close(fig)
        print('Wrote',ROOT/'evidence'/'benchmark.png')
    except ImportError:
        print('matplotlib not installed; skipped graph (CSV is still available)')
if __name__=='__main__': main()
