"""Minimal ComfyUI adapters for tests; never used by the installed extension."""

import atexit
import importlib
from pathlib import Path
import queue
import sys
import tempfile
import threading
import types

import numpy as np
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
temp = tempfile.TemporaryDirectory()
atexit.register(temp.cleanup)
interrupted = threading.Event()


class InterruptProcessingException(Exception):
    pass


def check_interrupt():
    if interrupted.is_set():
        interrupted.clear()
        raise InterruptProcessingException()


class Tensor(np.ndarray):
    """Only the IMAGE methods needed here, backed by real pixel arrays."""
    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return np.asarray(self)


def images(count=3, height=12, width=16):
    values = np.arange(count, dtype=np.float32) / max(count - 1, 1)
    return np.broadcast_to(values[:, None, None, None], (count, height, width, 3)).copy().view(Tensor)


class FakeServer:
    def __init__(self):
        self.client_id = "browser-a"
        self.routes = web.RouteTableDef()
        self.events = queue.Queue()
        self.on_event = None

    def send_sync(self, event, payload, sid=None):
        self.events.put((event, payload, sid))
        if self.on_event:
            self.on_event(event, payload, sid)


server = FakeServer()
context = types.SimpleNamespace(prompt_id="prompt-1")
model_management = types.ModuleType("comfy.model_management")
model_management.InterruptProcessingException = InterruptProcessingException
model_management.throw_exception_if_processing_interrupted = check_interrupt
comfy = types.ModuleType("comfy")
comfy.model_management = model_management
folder_paths = types.ModuleType("folder_paths")
folder_paths.get_temp_directory = lambda: temp.name
server_module = types.ModuleType("server")
server_module.PromptServer = types.SimpleNamespace(instance=server)
utils = types.ModuleType("comfy_execution.utils")
utils.get_executing_context = lambda: context
sys.modules.update({
    "comfy": comfy, "comfy.model_management": model_management,
    "folder_paths": folder_paths, "server": server_module,
    "comfy_execution": types.ModuleType("comfy_execution"),
    "comfy_execution.utils": utils,
})
package = importlib.import_module("Phluffhead_Custom_Nodes")
nodes = importlib.import_module("Phluffhead_Custom_Nodes.nodes")
state = importlib.import_module("Phluffhead_Custom_Nodes.selector_state")


def reset():
    interrupted.clear()
    server.client_id = "browser-a"
    server.events = queue.Queue()
    state.selections = state.SelectionStore()
    nodes.selections = state.selections


def start_pick(batch=None):
    result = queue.Queue()
    batch = images() if batch is None else batch

    def run():
        try:
            result.put(("selected", nodes.PickFromBatch().pick(batch, 0, mode="interactive", unique_id="7")[0]))
        except Exception as error:
            result.put(("error", error))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    return worker, result
