import json
from pathlib import Path
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bridge import PublishHandler, Store


class PortableStartupTests(unittest.TestCase):
    def test_callback_can_use_a_custom_local_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            ident = uuid.uuid4().hex
            store.submit(ident, 'Synthetic question', '')
            path = str(Path(directory) / 'reply.sock')
            server = socketserver.ThreadingUnixStreamServer(path, PublishHandler)
            server.daemon_threads = True
            server.store = store
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                result = subprocess.run([sys.executable, str(ROOT / 'src/publish_reply.py'), '--socket', path],
                                        input=json.dumps({'op': 'reply', 'job_id': ident, 'text': 'Full answer'}).encode(),
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0)
                self.assertTrue(json.loads(result.stdout)['ok'])
                self.assertEqual(store.get(ident)['answer'], 'Full answer')
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)

    def test_startup_never_overwrites_a_regular_file_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            path = state / 'publish.sock'
            original = state / 'keep.txt'
            original.write_text('Preserve this file')
            for is_link in (False, True):
                with self.subTest(symlink=is_link):
                    if is_link:
                        path.symlink_to(original)
                    else:
                        path.write_text('Preserve this file')
                    result = subprocess.run([sys.executable, str(ROOT / 'src/bridge.py'), '--state-dir', directory],
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(b'non-socket file', result.stderr)
                    self.assertEqual(path.read_text(), 'Preserve this file')
                    self.assertEqual(original.read_text(), 'Preserve this file')
                    path.unlink()


if __name__ == '__main__':
    unittest.main()
