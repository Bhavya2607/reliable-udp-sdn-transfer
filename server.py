import argparse
import hashlib
import os
import json
import socket
import time
from protocol import ACK, DATA, DONE, ERROR, FIN, READY, START, decode, encode


def emit_event(event, **fields):
    print('EVENT ' + json.dumps({'type': event, **fields}), flush=True)


def main():
    parser = argparse.ArgumentParser(description='Reliable UDP file receiver')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=5001)
    parser.add_argument('--output', default='received_files')
    args = parser.parse_args()
    os.makedirs(args.output, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sessions = {}
    completed = {}
    counters = {'received_data': 0, 'duplicate_packets': 0, 'out_of_order_packets': 0, 'completed_transfers': 0, 'rejected_packets': 0}
    print(f'UDP receiver listening on {args.host}:{args.port}')
    try:
        while True:
            packet, addr = sock.recvfrom(65535)
            msg = decode(packet)
            if not msg:
                continue
            kind, sid, seq, payload = msg
            key = (addr, sid)
            if kind == START:
                if len(payload) < 10:
                    sock.sendto(encode(ERROR, sid), addr)
                    continue
                name_len = int.from_bytes(payload[:2], 'big')
                size = int.from_bytes(payload[2:10], 'big')
                if name_len == 0 or len(payload) != 10 + name_len or size > 2**40:
                    sock.sendto(encode(ERROR, sid), addr)
                    continue
                name = os.path.basename(payload[10:].decode('utf-8', 'replace'))
                if not name or name in ('.', '..'):
                    sock.sendto(encode(ERROR, sid), addr)
                    continue
                if sid in completed:
                    # A delayed/retried START for a completed session must not recreate it.
                    sock.sendto(encode(DONE, sid, seq), addr)
                    continue
                if key not in sessions:
                    temp = os.path.join(args.output, f'.{sid.hex()}.part')
                    sessions[key] = {'name': name, 'size': size, 'total': seq, 'next': 0, 'buffer': {}, 'data': bytearray(), 'temp': temp, 'last': time.monotonic()}
                sock.sendto(encode(READY, sid), addr)
                emit_event('receiver_ready', filename=name, total_packets=seq, peer=str(addr))
                continue
            state = sessions.get(key)
            if state is None:
                if kind == FIN and sid in completed:
                    sock.sendto(encode(DONE, sid, seq), addr)
                continue
            state['last'] = time.monotonic()
            if kind == DATA:
                counters['received_data'] += 1
                emit_event('data_received', seq=seq, expected=state['next'], total=state['total'], peer=str(addr))
                if seq < state['next']:
                    counters['duplicate_packets'] += 1
                    print(f'Duplicate DATA seq={seq}; cumulative ACK={state["next"]}')
                    sock.sendto(encode(ACK, sid, state['next']), addr)
                    emit_event('ack_sent', ack=state['next'], duplicate=True, total=state['total'])
                    continue
                if seq >= state['total'] or len(payload) > 1000:
                    sock.sendto(encode(ERROR, sid), addr)
                    continue
                if seq > state['next']:
                    counters['out_of_order_packets'] += 1
                    print(f'Out-of-order DATA seq={seq}; waiting for seq={state["next"]}')
                if seq in state['buffer']:
                    counters['duplicate_packets'] += 1
                    print(f'Duplicate buffered DATA seq={seq}')
                state['buffer'].setdefault(seq, payload)
                while state['next'] in state['buffer']:
                    chunk = state['buffer'].pop(state['next'])
                    if len(state['data']) + len(chunk) > state['size']:
                        sock.sendto(encode(ERROR, sid), addr)
                        break
                    state['data'].extend(chunk)
                    state['next'] += 1
                sock.sendto(encode(ACK, sid, state['next']), addr)
                emit_event('ack_sent', ack=state['next'], duplicate=False, total=state['total'])
            elif kind == FIN:
                if len(payload) != 40 or seq != state['total']:
                    sock.sendto(encode(ERROR, sid), addr)
                    continue
                expected_size = int.from_bytes(payload[:8], 'big')
                expected_hash = payload[8:]
                data = bytes(state['data'])
                if state['next'] != state['total'] or len(data) != expected_size or expected_size != state['size'] or hashlib.sha256(data).digest() != expected_hash:
                    sock.sendto(encode(ERROR, sid), addr)
                    continue
                final_path = os.path.join(args.output, state['name'])
                temp_path = state['temp']
                with open(temp_path, 'wb') as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temp_path, final_path)
                sessions.pop(key, None)
                completed[sid] = time.monotonic()
                counters['completed_transfers'] += 1
                print('Receiver counters:', counters)
                sock.sendto(encode(DONE, sid, seq), addr)
                emit_event('integrity_verified', filename=state['name'], size=len(data), sha256=expected_hash.hex(), status='PASS')
                print(f'Received {state["name"]}: {len(data)} bytes; SHA-256 {expected_hash.hex()}')
            now = time.monotonic()
            for old_key, old_state in list(sessions.items()):
                if now - old_state['last'] > 300:
                    sessions.pop(old_key, None)
                    try:
                        os.remove(old_state['temp'])
                    except FileNotFoundError:
                        pass
            for old_sid, stamp in list(completed.items()):
                if now - stamp > 300:
                    completed.pop(old_sid, None)
    finally:
        sock.close()

if __name__ == '__main__':
    main()
