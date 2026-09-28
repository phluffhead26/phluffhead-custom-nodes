from .nodes import PickFromBatch, ReleaseModels
from .selector_state import register_routes
from server import PromptServer

WEB_DIRECTORY = "./web"

register_routes(PromptServer.instance)

NODE_CLASS_MAPPINGS = {
    "Phluffhead_PickFromBatch": PickFromBatch,
    "Phluffhead_ReleaseModels": ReleaseModels,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Phluffhead_PickFromBatch": "Pick from Batch",
    "Phluffhead_ReleaseModels": "Release Models Before Upscale",
}
