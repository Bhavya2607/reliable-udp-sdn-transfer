import hashlib
import struct
import zlib

MAGIC = b'RUDP'
HEADER = struct.Struct('!4sB16sIHI')
START, READY, DATA, ACK, FIN, DONE, ERROR = range(1, 8)
CHUNK_SIZE = 1000
WINDOW_SIZE = 32
TIMEOUT = 0.35
MAX_RETRIES = 30


def encode(kind, session, seq=0, payload=b''):
    checksum = zlib.crc32(payload) & 0xffffffff
    return HEADER.pack(MAGIC, kind, session, seq, len(payload), checksum) + payload


def decode(packet):
    if len(packet) < HEADER.size:
        return None
    magic, kind, session, seq, size, checksum = HEADER.unpack(packet[:HEADER.size])
    payload = packet[HEADER.size:]
    if magic != MAGIC or size != len(payload) or (zlib.crc32(payload) & 0xffffffff) != checksum:
        return None
    return kind, session, seq, payload


def sha256(data):
    return hashlib.sha256(data).digest()
