"""Allow installing the repository directly inside ComfyUI/custom_nodes."""

from .Phluffhead_Custom_Nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./Phluffhead_Custom_Nodes/web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
