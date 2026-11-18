import hashlib, os, socket, subprocess, sys, tempfile, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class TransferIntegrationTests(unittest.TestCase):
    def test_loopback_file_transfer_and_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); src=td/'payload.bin'; payload=os.urandom(180_000); src.write_bytes(payload)
            with socket.socket() as probe: probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
            server=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--host','127.0.0.1','--port',str(port),'--output',str(td/'out')],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                time.sleep(.2)
                result=subprocess.run([sys.executable,str(ROOT/'client.py'),str(src),'127.0.0.1','--port',str(port)],cwd=ROOT,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr+result.stdout)
                got=(td/'out'/'payload.bin').read_bytes()
                self.assertEqual(hashlib.sha256(got).digest(),hashlib.sha256(payload).digest())
                self.assertIn('retransmissions:',result.stdout)
            finally:
                server.terminate(); server.wait(timeout=5)

if __name__=='__main__': unittest.main()
