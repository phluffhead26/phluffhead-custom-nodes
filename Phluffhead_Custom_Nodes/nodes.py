"""Select an original image, optionally waiting for the browser to choose it."""

import shutil
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import folder_paths
from comfy import model_management
from comfy_execution.utils import get_executing_context
from server import PromptServer

from .selector_state import selections


def write_previews(images, directory):
    """Small, temporary PNGs only; output always uses the original tensor."""
    results = []
    for index, image in enumerate(images):
        model_management.throw_exception_if_processing_interrupted()
        pixels = (image.detach().cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        preview = Image.fromarray(pixels)
        preview.thumbnail((512, 512))
        filename = f"{index}.png"
        preview.save(directory / filename)
        results.append({"filename": filename, "subfolder": directory.name, "type": "temp"})
    return results


class PickFromBatch:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "index": ("INT", {"default": 0, "min": 0, "max": 2147483647, "step": 1}),
                "stop": ("BOOLEAN", {"default": False}),
            },
            # Append to preserve v0's widget order. API prompts that omit mode
            # keep manual behavior via pick's default.
            "optional": {"mode": (["interactive", "manual"],)},
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "pick"
    CATEGORY = "Phluffhead"
    DESCRIPTION = "Pause at this node, then choose an image to continue or Stop to cancel."

    @classmethod
    def IS_CHANGED(cls, mode="manual", **kwargs):
        # Only this node/downstream must run again; upstream keeps its cache.
        return float("nan") if mode == "interactive" else "manual"

    def pick(self, images, index, stop=False, mode="manual", unique_id=None):
        if stop:
            raise model_management.InterruptProcessingException()
        if len(images.shape) != 4 or len(images) == 0:
            raise ValueError("Pick from Batch needs a nonempty IMAGE batch [B,H,W,C].")
        if mode == "manual":
            index = max(0, min(int(index), len(images) - 1))
            return (images[index:index + 1],)
        if mode != "interactive":
            raise ValueError(f"Unknown Pick from Batch mode: {mode}")

        server = PromptServer.instance
        context = get_executing_context()
        client_id = server.client_id
        if not client_id or context is None or unique_id is None:
            raise ValueError("Interactive Pick from Batch needs a browser session. Use manual mode for API-only runs.")

        directory = Path(tempfile.mkdtemp(prefix="phluffhead-pick-", dir=folder_paths.get_temp_directory()))
        request = None
        outcome = "cancelled"
        try:
            previews = write_previews(images, directory)
            request = selections.create(str(unique_id), context.prompt_id, client_id, previews)
            server.send_sync("phluffhead.pick.pending", request.snapshot(), client_id)
            while True:
                # The HTTP/WebSocket server runs separately from this worker.
                # Poll so ComfyUI's own Cancel also works while paused.
                model_management.throw_exception_if_processing_interrupted()
                if request.event.wait(0.1):
                    model_management.throw_exception_if_processing_interrupted()
                    break
            if request.action == "stop":
                raise model_management.InterruptProcessingException()
            index = request.index
            outcome = "selected"
            return (images[index:index + 1],)
        finally:
            if request is not None:
                selections.remove(request.request_id)
                server.send_sync("phluffhead.pick.closed", {
                    "request_id": request.request_id,
                    "node_id": request.node_id,
                    "prompt_id": request.prompt_id,
                    "outcome": outcome,
                    "index": request.index if outcome == "selected" else None,
                }, client_id)
            shutil.rmtree(directory, ignore_errors=True)
