from .nodes import PickFromBatch
from .selector_state import register_routes
from server import PromptServer

WEB_DIRECTORY = "./web"

register_routes(PromptServer.instance)

NODE_CLASS_MAPPINGS = {
    "Phluffhead_PickFromBatch": PickFromBatch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Phluffhead_PickFromBatch": "Pick from Batch",
}
