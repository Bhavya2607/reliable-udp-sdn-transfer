import argparse
import hashlib
import json
import os
import secrets
import socket
import sys
import time
from protocol import ACK, CHUNK_SIZE, DATA, DONE, ERROR, FIN, MAX_RETRIES, READY, START, TIMEOUT, WINDOW_SIZE, decode, encode


def emit_event(event, **fields):
    print('EVENT ' + json.dumps({'type': event, **fields}), flush=True)


def transfer(path, host, port, sdn_controller=None):
    size = os.path.getsize(path)
    name = os.path.basename(path).encode('utf-8')
    session = secrets.token_bytes(16)
    with open(path, 'rb') as f:
        content = f.read()
    chunks = [content[i:i + CHUNK_SIZE] for i in range(0, len(content), CHUNK_SIZE)]
    digest = hashlib.sha256(content).digest()
    addr = (host, port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)
    start_payload = len(name).to_bytes(2, 'big') + size.to_bytes(8, 'big') + name
    start_packet = encode(START, session, len(chunks), start_payload)
    try:
        for attempt in range(MAX_RETRIES):
            sock.sendto(start_packet, addr)
            try:
                reply, _ = sock.recvfrom(2048)
                msg = decode(reply)
                if msg and msg[0] == READY and msg[1] == session:
                    break
            except socket.timeout:
                pass
        else:
            raise RuntimeError('Server did not acknowledge transfer setup')

        base = 0
        next_seq = 0
        outstanding = {}
        retries = 0
        total_packets_sent = len(chunks)
        emit_event('transfer_started', filename=os.path.basename(path), size=size, total_packets=len(chunks), chunk_size=CHUNK_SIZE, window_size=WINDOW_SIZE)
        retransmissions = 0
        started = time.monotonic()
        control = None
        if sdn_controller:
            control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            control.settimeout(0.25)
            control_addr = (sdn_controller, 9999)
        while base < len(chunks):
            while next_seq < len(chunks) and next_seq < base + WINDOW_SIZE:
                packet = encode(DATA, session, next_seq, chunks[next_seq])
                sock.sendto(packet, addr)
                outstanding[next_seq] = (packet, time.monotonic(), 0)
                emit_event('data_sent', seq=next_seq, base=base, window_end=min(base + WINDOW_SIZE - 1, len(chunks) - 1), total=len(chunks), retransmission=False)
                next_seq += 1
            try:
                reply, _ = sock.recvfrom(2048)
                msg = decode(reply)
                if msg and msg[1] == session:
                    kind, _, ack_next, _ = msg
                    if kind == ERROR:
                        raise RuntimeError('Server rejected a packet')
                    if kind == ACK and base <= ack_next <= next_seq:
                        for seq in range(base, ack_next):
                            outstanding.pop(seq, None)
                        old_base = base
                        base = ack_next
                        emit_event('ack_received', ack=ack_next, previous_base=old_base, base=base, outstanding=len(outstanding), total=len(chunks))
                        retries = 0
            except socket.timeout:
                pass

            # Check packet deadlines after EVERY receive, not only socket timeouts.
            # Duplicate cumulative ACKs can arrive continuously while a gap remains,
            # otherwise preventing socket.timeout and deadlocking the sliding window.
            now = time.monotonic()
            expired = [seq for seq, (_, sent, _) in outstanding.items() if now - sent >= TIMEOUT]
            if expired:
                for seq in expired:
                    packet, _, count = outstanding[seq]
                    if count >= MAX_RETRIES:
                        raise RuntimeError(f'Maximum retransmissions reached for packet {seq}')
                    sock.sendto(packet, addr)
                    outstanding[seq] = (packet, now, count + 1)
                    emit_event('retransmit', seq=seq, attempt=count + 1, cumulative_ack=base, total=len(chunks))
                    retries += 1
                    retransmissions += 1
                    total_packets_sent += 1
                if control:
                    try:
                        control.sendto(json.dumps({'event': 'transfer_stall', 'session': session.hex(), 'base': base, 'expired': expired, 'timestamp': time.time()}).encode(), control_addr)
                        control.sendto(b'{"event":"status"}', control_addr)
                        status, _ = control.recvfrom(2048)
                        print('SDN status:', status.decode(errors='replace'))
                    except (OSError, socket.timeout):
                        print('SDN telemetry unavailable; continuing UDP recovery')
                print(f'Retransmitting {len(expired)} packet(s); cumulative ACK={base}')

        fin_packet = encode(FIN, session, len(chunks), size.to_bytes(8, 'big') + digest)
        for _ in range(MAX_RETRIES):
            sock.sendto(fin_packet, addr)
            try:
                reply, _ = sock.recvfrom(2048)
                msg = decode(reply)
                if msg and msg[1] == session and msg[0] == DONE:
                    elapsed = time.monotonic() - started
                    emit_event('transfer_completed', size=size, sha256=digest.hex(), elapsed=elapsed, throughput_mbps=(size * 8 / elapsed / 1_000_000) if elapsed else 0, transmissions=total_packets_sent, retransmissions=retransmissions, acknowledged=len(chunks))
                    print(f'Transfer successful: {size} bytes in {elapsed:.3f}s')
                    print(f'SHA-256: {digest.hex()}')
                    throughput = (size * 8 / elapsed / 1_000_000) if elapsed else 0
                    print(f'Approx. throughput: {throughput:.3f} Mbps')
                    print(f'Total DATA transmissions: {total_packets_sent}; retransmissions: {retransmissions}')
                    print(f'Packets acknowledged cumulatively: {len(chunks)}')
                    print(f'Elapsed seconds: {elapsed:.6f}')
                    return
                if msg and msg[0] == ERROR:
                    raise RuntimeError('Server integrity check failed')
            except socket.timeout:
                continue
        raise RuntimeError('Server did not confirm transfer completion')
    finally:
        sock.close()
        if 'control' in locals() and control:
            control.close()


def main():
    parser = argparse.ArgumentParser(description='Reliable UDP file sender (selective retransmission with cumulative ACKs)')
    parser.add_argument('file')
    parser.add_argument('server_ip')
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--sdn-controller', help='Reachable management IP of controller telemetry listener (UDP/9999)')
    args = parser.parse_args()
    if not os.path.isfile(args.file):
        parser.error('Input file does not exist')
    try:
        transfer(args.file, args.server_ip, args.port, args.sdn_controller)
    except (OSError, RuntimeError) as exc:
        print(f'Transfer failed: {exc}', file=sys.stderr)
        raise SystemExit(1)

if __name__ == '__main__':
    main()
