"""Local HTTP host for the real extension; ComfyUI host APIs are stubbed."""
import asyncio
import json
from pathlib import Path
import uuid

from aiohttp import web
import support as s

ROOT = Path(__file__).resolve().parents[1]
worker = None
result_queue = None
outcome = None
sockets = set()

APP_JS = '''
export const app = {
  registerExtension(extension) { window.extension = extension; extension.setup(); }
};
'''
API_JS = '''
export const api = new EventTarget();
api.clientId = "browser-a";
api.apiURL = (path) => path;
api.fetchApi = (path, options) => {
  if (path === "/phluffhead/pick/respond") window.submitCount = (window.submitCount || 0) + 1;
  return fetch(path, options);
};
api.socket = new WebSocket(`ws://${location.host}/ws`);
api.socket.onmessage = ({data}) => {
  const event = JSON.parse(data);
  api.dispatchEvent(new CustomEvent(event.type, {detail: event.data}));
};
api.socket.onopen = () => {
  window.connected = true;
  api.dispatchEvent(new CustomEvent("status", {detail: {}}));
};
window.api = api;
'''
HTML = '''<!doctype html><html><head><title>Pick from Batch test host</title></head>
<body style="background:#181818;color:white;font-family:sans-serif">
<h2>Pick from Batch — extension test host</h2><div id="node" style="width:360px;height:340px"></div>
<script type="module">
import {api} from '/scripts/api.js';
import '/extensions/phluffhead/pick_from_batch.js';
const node = {
  id: 7, comfyClass: 'Phluffhead_PickFromBatch', size: [360,490],
  addDOMWidget(name, type, root, options) { document.querySelector('#node').append(root); return {}; },
  setSize(size) { this.size = size; }, setDirtyCanvas() {}
};
window.extension.nodeCreated(node);
window.extension.afterConfigureGraph();
window.node = node;
window.ready = true;
</script></body></html>'''


async def main():
    s.reset()
    loop = asyncio.get_running_loop()
    async def publish(event, payload, sid):
        for ws in list(sockets):
            if not ws.closed:
                await ws.send_json({"type": event, "data": payload})
    s.server.on_event = lambda *args: asyncio.run_coroutine_threadsafe(publish(*args), loop)
    app = web.Application()
    app.add_routes(s.server.routes)

    async def index(request):
        return web.Response(text=HTML, content_type="text/html")

    async def app_js(request):
        return web.Response(text=APP_JS, content_type="text/javascript")

    async def api_js(request):
        return web.Response(text=API_JS, content_type="text/javascript")

    async def extension(request):
        return web.FileResponse(ROOT / 'Phluffhead_Custom_Nodes/web/pick_from_batch.js')

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        sockets.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            sockets.discard(ws)
        return ws

    async def preview(request):
        path = (Path(s.temp.name) / request.query['subfolder'] / request.query['filename']).resolve()
        if not path.is_relative_to(Path(s.temp.name).resolve()):
            raise web.HTTPForbidden()
        return web.FileResponse(path)

    async def start(request):
        global worker, result_queue, outcome
        if worker and worker.is_alive():
            return web.json_response({"error": "Already waiting"}, status=409)
        s.context.prompt_id = uuid.uuid4().hex
        s.interrupted.clear()
        outcome = None
        worker, result_queue = s.start_pick(s.images(4))
        return web.json_response({"prompt_id": s.context.prompt_id})

    async def result(request):
        global outcome
        if outcome is None and result_queue is not None and not result_queue.empty():
            state, value = result_queue.get_nowait()
            if state == "selected":
                outcome = {"state": "selected", "shape": list(value.shape), "value": float(value[0, 0, 0, 0])}
            else:
                outcome = {"state": "stopped" if isinstance(value, s.InterruptProcessingException) else "error", "error": str(value)}
        return web.json_response(outcome or {"state": "waiting"})

    async def cancel(request):
        s.interrupted.set()
        return web.json_response({"ok": True})

    app.add_routes([
        web.get('/', index), web.get('/scripts/app.js', app_js), web.get('/scripts/api.js', api_js),
        web.get('/extensions/phluffhead/pick_from_batch.js', extension), web.get('/ws', ws_handler),
        web.get('/view', preview), web.post('/test/start', start), web.get('/test/result', result),
        web.post('/test/cancel', cancel),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    print(f'http://127.0.0.1:{port}', flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        s.interrupted.set()
        await runner.cleanup()


if __name__ == '__main__':
    asyncio.run(main())
