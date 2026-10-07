"""Official SDK transport restricted to Kindle answers and inbox delivery."""
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys

from musegadget import config, identity
from musegadget.executor import Account, Executor
from musegadget import service as sdk_service

KINDLE_COMMANDS = {
    "kindle.publish": {
        "description": "Publish the COMPLETE plain-text answer to a pending Kindle reader request. Use the exact job_id from its message. Does not execute commands or access arbitrary files.",
        "required": {
            "job_id": {"type": "string", "description": "32 lowercase hex characters identifying the pending Kindle request."},
            "text": {"type": "string", "description": "Complete answer, plain text, 1 to 60000 characters. Call once after finishing the answer."},
        },
        "optional": {},
    },
    "kindle.notify": {
        "description": "Send a new plain-text message to the user's private Kindle inbox. Before any kindle-news-* delivery, call kindle.news_source for EVERY article URL in text and use only fresh=true sources; the inbox rejects unverified news. No pending reader question is needed. Success means saved, not proof the screen is awake.",
        "required": {
            "delivery_id": {"type": "string", "description": "Stable unique ID for this delivery, 1 to 128 ASCII letters/digits or _ . : -. For daily news use kindle-news-YYYY-MM-DD with the Asia/Shanghai date. Reuse the same ID and EXACT content when retrying."},
            "title": {"type": "string", "description": "Short descriptive Chinese title, 1 to 160 characters."},
            "text": {"type": "string", "description": "Complete plain-text message, 1 to 60000 characters. News must include verified source URLs and dates."},
        },
        "optional": {},
    },
    "kindle.news_source": {
        "description": "Verify a public news article's publication date from the publisher page on this bridge host. Call for every source before kindle.notify news delivery. Exclude fresh=false and errors; never change an old publication year. Only approved public HTTPS news/publisher hosts are accepted. A fresh date does not by itself prove every claim in your summary.",
        "required": {"url": {"type": "string", "description": "Direct HTTPS article URL. Approved hosts include www.news.cn, news.cctv.com, www.reuters.com, apnews.com, www.bbc.com, www.bbc.co.uk, www.theguardian.com, www.nytimes.com, cn.nytimes.com, www.ft.com, www.france24.com, openai.com, www.anthropic.com, ai.meta.com."}},
        "optional": {},
    },
}


class KindleExecutor(Executor):
    def run(self, command, params, timeout_ms=None):
        if command not in KINDLE_COMMANDS or not isinstance(params, dict):
            return {"ok": False, "error": "unsupported Kindle command"}
        try:
            if command == "kindle.publish":
                payload = {"op": "reply", "job_id": params.get("job_id"), "text": params.get("text")}
            elif command == "kindle.notify":
                payload = {"op": "notify", "delivery_id": params.get("delivery_id"), "title": params.get("title"), "text": params.get("text")}
            else:
                payload = {"op": "news_source", "url": params.get("url")}
            data = json.dumps(payload, ensure_ascii=False).encode()
            if len(data) > 256000:
                raise ValueError("packet too large")
            process = subprocess.run(
                [sys.executable, os.path.join(os.path.dirname(__file__), "publish_reply.py"),
                 "--socket", os.environ.get("KINDLE_MUSE_PUBLISH_SOCKET", "/run/kindle-muse-bridge/publish.sock")],
                input=data, capture_output=True, timeout=20 if command == "kindle.news_source" else 10, cwd="/",
                **self._child_options(),
            )
            result = json.loads(process.stdout)
            if result.get("ok") is True:
                if command == "kindle.news_source":
                    return {"ok": True, "payload": result["source"]}
                return {"ok": True, "payload": {"published": True, "duplicate": result.get("duplicate", False),
                                                "message_id": result.get("message_id")}}
            return {"ok": False, "error": result.get("error", "Kindle request rejected")}
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return {"ok": False, "error": "Kindle reply rejected or reader unavailable"}


class KindleService(sdk_service.Service):
    async def _session(self, vm, pairing):
        outcome, lasted = await super()._session(vm, pairing)
        self.last_outcome = outcome
        return outcome, lasted

    async def _local_request(self, line):
        request = json.loads(line)
        if isinstance(request, dict) and request.get("op") == "status":
            connected = self._current is not None and self._current.registered_at is not None
            rejected = getattr(self, "last_outcome", None) is sdk_service.Outcome.FORBIDDEN
            return {"ok": True, "paired": config.load_json(config.PAIRING_FILE) is not None,
                    "connected": connected, "cloud_rejected": rejected and not connected}
        return await super()._local_request(line)


async def main():
    # Keep upstream pairing and encrypted transport unchanged; replace the
    # registry used by Service._session before any device registration.
    sdk_service.COMMAND_SPECS = KINDLE_COMMANDS
    account = Account.lookup(os.environ.get("MUSEGADGET_RUN_AS", "kindle-muse"))
    service = KindleService(identity=identity.load_or_create(), executor=KindleExecutor(account),
                            sdk_token=config.sdk_token(),
                            display_name=os.environ.get("KINDLE_MUSE_DISPLAY_NAME", "Kindle Muse Reader"))
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, service.stop)
    server = await service.serve_local(config.socket_path())
    try:
        await service.run()
    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
