# Phluffhead Custom Nodes (ComfyUI)

## Pick from Batch

Generate a batch, pause, and click **Pick 1…N** to send one original image
through the rest of your workflow. **Stop** cancels the active prompt.

Connect: **VAE Decode → Pick from Batch → your next image node / Save Image**.
Find the node under **Phluffhead → Pick from Batch**. Connect it to a downstream
output (such as Save Image) so ComfyUI actually executes the branch.

- **mode = interactive:** previews appear in the node when execution reaches it.
  Click a thumbnail/Pick button to continue the same run. No re-queue or re-sampling.
- **mode = manual:** select using the zero-based `index` widget; no pause.
- Leave the legacy `stop` Boolean **false**. If true, it cancels when the node runs.
  Use the live **Stop** button while paused.
- Preview thumbnails are at most 512 pixels. The output is the original tensor
  slice, with a batch size of one, unchanged resolution, dtype, and device.
- ComfyUI's normal **Cancel/Interrupt** also works while waiting. Stop cancels the
  current prompt, not all queued prompts; it cannot undo nodes already executed.
- Every interactive execution asks again, even with unchanged inputs. Normal
  upstream caching is retained.

## Install on RunPod (interactive test branch)

Stop ComfyUI before installing. Run the following from **your actual ComfyUI
folder** (often `/workspace/ComfyUI`, but templates vary):

```bash
cd custom_nodes
git clone --branch codex/interactive-pick-from-batch https://github.com/phluffhead26/phluffhead-custom-nodes.git
```

The interactive version is on this review branch until merged; cloning the
default branch before then installs the old numeric selector.

If this repository is already a Git checkout, switch that checkout to the branch
and pull it after checking for local edits. Do not install a second copy.

If you previously copied only the `Phluffhead_Custom_Nodes` folder, move that old
folder **outside `custom_nodes`** as a backup before cloning. Keeping two copies
can cause duplicate route/node registration. The old folder-copy installation
still works if you replace it with the complete updated inner folder, including
its `web` directory.

Restart ComfyUI, then refresh its browser page. No additional dependencies beyond
ComfyUI's existing NumPy, Pillow and aiohttp are required. The repository can now
be cloned directly into `custom_nodes` because it has a root loader.

## Compatibility and limits

- Uses legacy node/extension hooks present at ComfyUI `e89b2299` and inspected in
  `a73d24ba` (September 2026); frontend hooks inspected at `v1.53.6`.
- Existing node identifiers and the first three widget positions are preserved.
  Set `mode` explicitly when opening an older workflow. API prompts that omit
  `mode` retain the original manual behavior.
- Interactive mode needs the browser client that queued the prompt. API-only
  runs should use `mode: "manual"`.
- Keep the workflow open in the originating tab. Refresh/reconnect can recover
  pending choices when ComfyUI retains that tab's client ID. A different browser
  session cannot take over the choice; use native Cancel if the original session
  is lost. Pending choices do not survive a server restart.
- This v1 targets ordinary nodes in the main workflow, not selectors inside
  subgraphs. It holds the prompt worker, so subsequent queued prompts wait too.
- Preview files are temporary and removed on selection/cancellation. Save Image
  still embeds the queued workflow/prompt normally; live selection is not written
  back into that already-queued prompt as a reproducible manual index.

## RunPod portrait starter

`scripts/setup_runpod_portrait.py` uses the running ComfyUI API (default port
3000) to check installed nodes and model menus before changing files. Run it
from this complete repository checkout with an idle queue. It locates the running
ComfyUI process, backs up the existing package outside `custom_nodes`, updates
our four package files, and adds a new timestamped workflow through `/userdata`.
It does not queue images or restart the server. Use `--dry-run` to check first,
`--root /path/to/ComfyUI` if process discovery fails, or `--user ID` for multi-user
servers. Existing workflows are preserved. Restart ComfyUI and refresh afterward.

The separate `examples/Phluffhead_TwoPerson_Portrait_SeedVR2.json` is an experimental
fully clothed portrait starter. Select two reference images before queuing. Two
single-image samplers feed the interactive selector; the selected base and its
SeedVR2 upscale are both saved. The new Release Models Before Upscale node passes
images through unchanged while unloading ComfyUI-managed models and clearing its
cache to make VRAM available to the external upscaler.

Defaults target a 24 GB GPU: roughly 1 MP generation, SeedVR2 3B FP8, tiled VAE,
CPU offloading, and 1536 px short edge capped at 2048 px long edge. This is not a
verified VRAM guarantee. SeedVR2 may download weights on first use. Reference
slots remain asymmetric; this graph does not turn them into separate identity
embeddings or guarantee better likeness. Compare the saved base and upscale.
The example has not yet been executed on a real ComfyUI GPU installation.

## Verification

Backend tests (no models/GPU required):

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Browser integration test (requires Node, Playwright and its Chromium browser):

```bash
node tests/browser.mjs
```

These tests exercise the real node and HTTP routes against small ComfyUI adapter
stubs and a NumPy tensor stand-in. Browser tests mount the real extension with
stubbed ComfyUI host APIs. They do not replace a live ComfyUI/RunPod smoke test.

Before treating v1 as production-ready, queue a real image batch on RunPod,
choose its first and last images on separate runs, verify the downstream saved
image, repeat with the same inputs, and try both Stop and native Cancel. Refresh
while paused and confirm the grid returns. The active frontend's actual node
layout and real tensor execution still need that smoke test.

## License

MIT
