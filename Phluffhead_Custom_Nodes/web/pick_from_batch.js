import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const controllers = new Set();
let eventVersion = 0;

function makeController(node) {
    const root = document.createElement("div");
    root.className = "phluffhead-picker";
    root.style.cssText = "display:flex;flex-direction:column;gap:8px;height:100%;box-sizing:border-box;padding:8px;color:var(--input-text,#eee);background:var(--comfy-input-bg,#222);font:13px sans-serif;overflow:auto;";
    const status = document.createElement("div");
    status.setAttribute("role", "status");
    status.textContent = "Queue in interactive mode to preview and choose an image.";
    const grid = document.createElement("div");
    grid.style.cssText = "display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;overflow:auto;flex:1;min-height:0;";
    const stop = document.createElement("button");
    stop.textContent = "Stop";
    stop.type = "button";
    stop.style.cssText = "background:#8c3030;color:white;padding:8px;border:0;border-radius:4px;cursor:pointer;";
    stop.hidden = true;
    root.append(status, grid, stop);
    for (const event of ["pointerdown", "mousedown", "wheel"]) {
        root.addEventListener(event, (e) => e.stopPropagation());
    }
    const widget = node.addDOMWidget("phluffhead_picker", "phluffhead_picker", root, {
        serialize: false, getMinHeight: () => 180, getHeight: () => 340,
    });
    widget.computeSize = (width) => [width, 340];
    node.setSize([Math.max(node.size[0], 360), Math.max(node.size[1], 490)]);

    let current = null;
    let submitting = false;
    const setDisabled = (disabled) => {
        for (const button of root.querySelectorAll("button")) button.disabled = disabled;
    };

    async function submit(action, index) {
        if (!current || submitting) return;
        const request = current;
        submitting = true;
        setDisabled(true);
        status.textContent = action === "stop" ? "Stopping…" : `Choosing image ${index + 1}…`;
        try {
            const response = await api.fetchApi("/phluffhead/pick/respond", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ request_id: request.request_id, client_id: api.clientId, action, index }),
            });
            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || `Selection failed (${response.status}).`);
            }
            // A reply may arrive after the worker's closed event or next request.
        } catch (error) {
            if (current?.request_id !== request.request_id) return;
            submitting = false;
            status.textContent = `${error.message} You can retry or use ComfyUI's Cancel.`;
            setDisabled(false);
        }
    }
    stop.addEventListener("click", () => submit("stop"));

    const controller = {
        node,
        show(request) {
            if (current?.request_id === request.request_id) return;
            current = request;
            submitting = false;
            status.textContent = `Paused — choose 1 of ${request.images.length} images to continue.`;
            grid.replaceChildren();
            for (const [index, descriptor] of request.images.entries()) {
                const button = document.createElement("button");
                button.type = "button";
                button.setAttribute("aria-label", `Pick ${index + 1}`);
                button.title = `Continue with image ${index + 1}`;
                button.style.cssText = "display:flex;flex-direction:column;gap:6px;align-items:center;padding:6px;background:var(--comfy-menu-bg,#333);color:inherit;border:1px solid #666;border-radius:5px;cursor:pointer;";
                const image = document.createElement("img");
                image.alt = `Image ${index + 1}`;
                image.src = api.apiURL(`/view?${new URLSearchParams(descriptor)}`);
                image.style.cssText = "width:100%;height:120px;object-fit:contain;";
                const label = document.createElement("span");
                label.textContent = `Pick ${index + 1}`;
                button.append(image, label);
                button.addEventListener("click", () => submit("pick", index));
                grid.append(button);
            }
            stop.hidden = false;
            setDisabled(false);
            node.setDirtyCanvas(true, true);
        },
        close(event) {
            if (!current || event.request_id !== current.request_id) return;
            current = null;
            submitting = false;
            grid.replaceChildren();
            stop.hidden = true;
            status.textContent = event.outcome === "selected"
                ? `Image ${event.index + 1} selected. Workflow continued.`
                : event.outcome === "finished"
                    ? "This selection is no longer pending. Queue again when ready."
                    : "Selection cancelled. Queue again when ready.";
        },
        reconcile(requestIds) {
            if (current && !requestIds.has(current.request_id)) {
                this.close({ request_id: current.request_id, outcome: "finished" });
            }
        },
        endPrompt(event) {
            if (current?.prompt_id === event.prompt_id) {
                this.close({ request_id: current.request_id, outcome: "cancelled" });
            }
        },
        dispose() {
            // Removing a paused node should not leave the worker stranded.
            if (current && !submitting) void submit("stop");
            controllers.delete(controller);
            root.remove();
        },
    };
    const oldRemoved = node.onRemoved;
    node.onRemoved = function (...args) {
        controller.dispose();
        return oldRemoved?.apply(this, args);
    };
    return controller;
}

function showPending(request) {
    for (const controller of controllers) {
        if (String(controller.node.id) === request.node_id) controller.show(request);
    }
}

async function restorePending() {
    if (!api.clientId) return;
    const version = eventVersion;
    try {
        const response = await api.fetchApi(`/phluffhead/pick/pending?${new URLSearchParams({ client_id: api.clientId })}`, { cache: "no-store" });
        if (!response.ok) return;
        const { pending } = await response.json();
        // A newer live event supersedes an in-flight HTTP snapshot.
        if (version !== eventVersion) return;
        const requestIds = new Set(pending.map((request) => request.request_id));
        for (const controller of controllers) controller.reconcile(requestIds);
        for (const request of pending) showPending(request);
    } catch (error) {
        console.debug("Phluffhead: could not restore pending selection", error);
    }
}

app.registerExtension({
    name: "Phluffhead.PickFromBatch",
    setup() {
        api.addEventListener("phluffhead.pick.pending", ({ detail }) => {
            eventVersion++;
            showPending(detail);
        });
        api.addEventListener("phluffhead.pick.closed", ({ detail }) => {
            eventVersion++;
            for (const controller of controllers) controller.close(detail);
        });
        for (const event of ["execution_interrupted", "execution_error", "execution_success"]) {
            api.addEventListener(event, ({ detail }) => {
                eventVersion++;
                for (const controller of controllers) controller.endPrompt(detail);
            });
        }
        api.addEventListener("status", restorePending);
        api.addEventListener("reconnected", restorePending);
    },
    nodeCreated(node) {
        if (node.comfyClass !== "Phluffhead_PickFromBatch") return;
        controllers.add(makeController(node));
    },
    afterConfigureGraph() {
        void restorePending();
    },
});
