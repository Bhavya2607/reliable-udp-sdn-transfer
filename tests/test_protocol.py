import os
import sys
import unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from protocol import ACK, DATA, decode, encode

class ProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        sid = bytes(range(16))
        packet = encode(DATA, sid, 42, b'hello')
        self.assertEqual(decode(packet), (DATA, sid, 42, b'hello'))

    def test_corruption_rejected(self):
        packet = bytearray(encode(ACK, b'x' * 16, 3, b''))
        packet[-1:] = b'z'
        self.assertIsNone(decode(bytes(packet)))

if __name__ == '__main__':
    unittest.main()
