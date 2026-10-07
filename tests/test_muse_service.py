import asyncio
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    import muse_service
except ImportError:
    muse_service = None


@unittest.skipIf(muse_service is None, "Optional official Muse Gadget SDK is not installed")
class NarrowCommandsTests(unittest.TestCase):
    def test_only_reader_delivery_commands_are_advertised(self):
        self.assertEqual(set(muse_service.KINDLE_COMMANDS), {"kindle.publish", "kindle.notify", "kindle.news_source"})

    def test_shell_and_arbitrary_file_access_are_rejected(self):
        executor = muse_service.KindleExecutor(None)
        for name in ("system.run", "file.read", "file.write", "device.health"):
            self.assertFalse(executor.run(name, {"command": "id", "path": "/etc/passwd"})["ok"])

    def test_local_status_cannot_echo_credentials(self):
        service = muse_service.KindleService(identity=None, executor=None)
        with patch("muse_service.config.load_json", return_value=None):
            reply = asyncio.run(service._local_request(b'{"op":"status"}'))
        self.assertEqual(set(reply), {"ok", "paired", "connected", "cloud_rejected"})
        self.assertFalse(reply["connected"])

    def test_forbidden_is_visible_without_exposing_credentials(self):
        service = muse_service.KindleService(identity=None, executor=None)
        service.last_outcome = muse_service.sdk_service.Outcome.FORBIDDEN
        with patch("muse_service.config.load_json", return_value={}):
            reply = asyncio.run(service._local_request(b'{"op":"status"}'))
        self.assertTrue(reply["paired"])
        self.assertTrue(reply["cloud_rejected"])

    def test_custom_reply_socket_does_not_inherit_sdk_credentials(self):
        executor = muse_service.KindleExecutor(None)
        with patch.dict(os.environ, {"KINDLE_MUSE_PUBLISH_SOCKET": "/run/custom-reader/reply.sock",
                                     "MUSEGADGET_SDK_TOKEN": "not-a-real-token"}), \
             patch.object(executor, "_child_options", return_value={"env": {"PATH": "/usr/bin"}}), \
             patch("muse_service.subprocess.run") as run:
            run.return_value.stdout = json.dumps({"ok": True}).encode()
            reply = executor.run("kindle.publish", {"job_id": "a" * 32, "text": "Complete answer"})
        self.assertTrue(reply["ok"])
        self.assertEqual(run.call_args.args[0][-2:], ["--socket", "/run/custom-reader/reply.sock"])
        self.assertNotIn("MUSEGADGET_SDK_TOKEN", run.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
