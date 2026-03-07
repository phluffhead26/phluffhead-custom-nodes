class PickFromBatch:
    """Pick a single image from an IMAGE batch by index.

    v0: Python-only. UI is a simple index selector + optional stop.

    ComfyUI note: IMAGE is typically a torch tensor batch shaped like [B,H,W,C]
    (or similar depending on pipeline). Indexing with images[index] is safe.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "index": ("INT", {"default": 0, "min": 0, "max": 63, "step": 1}),
                "stop": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "pick"
    CATEGORY = "Phluffhead"

    def pick(self, images, index, stop=False):
        if stop:
            # Standard pattern in ComfyUI: raising interrupts the prompt.
            raise Exception("Phluffhead PickFromBatch: stopped by user")

        # Clamp index to available batch
        try:
            batch = len(images)
        except Exception:
            batch = None

        if batch is not None and batch > 0:
            if index < 0:
                index = 0
            if index >= batch:
                index = batch - 1

        selected = images[index]

        # ComfyUI expects IMAGE output to be a batch, even for a single image.
        # Most nodes use images[:1] style, but selected.unsqueeze(0) is clearer.
        try:
            selected = selected.unsqueeze(0)
        except Exception:
            # Fallback: if it's already batched
            pass

        return (selected,)
