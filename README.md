# Phluffhead Custom Nodes (ComfyUI)

A small collection of ComfyUI custom nodes.

## Install

1. Close ComfyUI
2. Copy this folder into your ComfyUI `custom_nodes` directory so you have:

   `ComfyUI/custom_nodes/Phluffhead_Custom_Nodes/`

3. Restart ComfyUI
4. In the node menu you should see: **Phluffhead → Pick from Batch**

## Nodes

### Pick from Batch (v0)

- **Category:** `Phluffhead`
- **Inputs:**
  - `images` (IMAGE batch)
  - `index` (INT)
  - `stop` (BOOLEAN) — if true, stops the prompt
- **Outputs:**
  - `image` (IMAGE)

Notes:
- This v0 node is Python-only (no in-node button UI yet). It’s intended as a stable base.
- The selected image remains compatible with `SaveImage` metadata embedding (workflow/prompt).

## Roadmap

- v1: in-node preview grid + Pick 1..N buttons + Stop, single-node UX.

## License

MIT
