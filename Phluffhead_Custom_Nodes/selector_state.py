"""Thread-safe bridge between ComfyUI's prompt worker and HTTP server."""

import json
import threading
import uuid
from dataclasses import dataclass, field

from aiohttp import web


class SelectionError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


@dataclass
class Selection:
    node_id: str
    prompt_id: str
    client_id: str
    images: list
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    event: threading.Event = field(default_factory=threading.Event)
    action: str = None
    index: int = None

    def snapshot(self):
        return {
            "request_id": self.request_id, "node_id": self.node_id,
            "prompt_id": self.prompt_id, "images": self.images,
        }


class SelectionStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests = {}

    def create(self, node_id, prompt_id, client_id, images):
        request = Selection(node_id, prompt_id, client_id, images)
        with self._lock:
            self._requests[request.request_id] = request
        return request

    def pending(self, client_id):
        with self._lock:
            return [r.snapshot() for r in self._requests.values()
                    if r.client_id == client_id and not r.event.is_set()]

    def resolve(self, request_id, client_id, action, index=None):
        with self._lock:
            request = self._requests.get(request_id)
            if request is None:
                raise SelectionError(404, "This selection has expired. Queue the workflow again.")
            if request.client_id != client_id:
                raise SelectionError(403, "Use the browser session that queued this workflow.")
            if request.event.is_set():
                raise SelectionError(409, "This selection has already been submitted.")
            if action not in ("pick", "stop"):
                raise SelectionError(400, "Action must be pick or stop.")
            if action == "pick" and (type(index) is not int or not 0 <= index < len(request.images)):
                raise SelectionError(400, "Pick an image from the displayed batch.")
            request.action = action
            request.index = index if action == "pick" else None
            request.event.set()

    def remove(self, request_id):
        with self._lock:
            self._requests.pop(request_id, None)


selections = SelectionStore()


def register_routes(server):
    @server.routes.get("/phluffhead/pick/pending")
    async def pending(request):
        client_id = request.query.get("client_id")
        if not client_id:
            return web.json_response({"error": "Missing browser session."}, status=400)
        return web.json_response({"pending": selections.pending(client_id)},
                                 headers={"Cache-Control": "no-store"})

    @server.routes.post("/phluffhead/pick/respond")
    async def respond(request):
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise SelectionError(400, "Expected a JSON object.")
            for key in ("request_id", "client_id"):
                if not isinstance(data.get(key), str) or not data[key]:
                    raise SelectionError(400, f"Missing or invalid {key}.")
            selections.resolve(data["request_id"], data["client_id"], data.get("action"), data.get("index"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.json_response({"error": "Expected valid JSON."}, status=400)
        except SelectionError as error:
            return web.json_response({"error": str(error)}, status=error.status)
        return web.json_response({"ok": True})
