import math
from pathlib import Path
import unittest

import numpy as np
from PIL import Image
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import support as s


class NodeTests(unittest.TestCase):
    def setUp(self):
        s.reset()

    def start(self, batch=None):
        worker, result = s.start_pick(batch)
        def cleanup():
            if worker.is_alive():
                s.interrupted.set()
                worker.join(2)
            self.assertFalse(worker.is_alive(), "Prompt worker was stranded")
        self.addCleanup(cleanup)
        event, request, client = s.server.events.get(timeout=2)
        self.assertEqual(event, "phluffhead.pick.pending")
        self.assertEqual(client, "browser-a")
        self.assertTrue(worker.is_alive())
        self.assertTrue(result.empty(), "Returned before user choice")
        return worker, result, request

    def assert_clean(self, request):
        self.assertEqual(s.state.selections.pending("browser-a"), [])
        self.assertFalse((Path(s.temp.name) / request["images"][0]["subfolder"]).exists())

    def test_manual_legacy_and_clamping(self):
        batch = s.images()
        for index, expected in [(-1, 0), (1, 1), (999, 2)]:
            out, = s.nodes.PickFromBatch().pick(batch, index)
            np.testing.assert_array_equal(out, batch[expected:expected + 1])
            self.assertTrue(np.shares_memory(out, batch))
        self.assertTrue(s.server.events.empty())

    def test_pause_then_first_and_last_original_image(self):
        batch = s.images()
        for index in [0, 2]:
            worker, result, request = self.start(batch)
            s.state.selections.resolve(request["request_id"], "browser-a", "pick", index)
            worker.join(2)
            outcome, out = result.get(timeout=1)
            self.assertEqual(outcome, "selected")
            np.testing.assert_array_equal(out, batch[index:index + 1])
            self.assertEqual(out.dtype, batch.dtype)
            self.assertTrue(np.shares_memory(out, batch))
            self.assert_clean(request)
            s.server.events.get(timeout=1)  # closed

    def test_thumbnail_size_does_not_change_output(self):
        batch = s.images(1, 600, 900)
        worker, result, request = self.start(batch)
        descriptor = request["images"][0]
        with Image.open(Path(s.temp.name) / descriptor["subfolder"] / descriptor["filename"]) as preview:
            self.assertEqual(preview.size, (512, 341))
        s.state.selections.resolve(request["request_id"], "browser-a", "pick", 0)
        worker.join(2)
        self.assertEqual(result.get(timeout=1)[1].shape, (1, 600, 900, 3))

    def test_live_stop_and_native_cancel(self):
        for native in [False, True]:
            worker, result, request = self.start()
            if native:
                s.interrupted.set()
            else:
                s.state.selections.resolve(request["request_id"], "browser-a", "stop")
            worker.join(2)
            outcome, error = result.get(timeout=1)
            self.assertEqual(outcome, "error")
            self.assertIsInstance(error, s.InterruptProcessingException)
            self.assert_clean(request)
            event, payload, _ = s.server.events.get(timeout=1)
            self.assertEqual(payload["outcome"], "cancelled")

    def test_empty_batch_and_legacy_stop(self):
        with self.assertRaises(ValueError):
            s.nodes.PickFromBatch().pick(s.images(0), 0)
        with self.assertRaises(s.InterruptProcessingException):
            s.nodes.PickFromBatch().pick(s.images(), 0, stop=True)

    def test_interactive_cache_and_manual_cache(self):
        self.assertTrue(math.isnan(s.nodes.PickFromBatch.IS_CHANGED(mode="interactive")))
        self.assertEqual(s.nodes.PickFromBatch.IS_CHANGED(), "manual")

    def test_browser_required(self):
        s.server.client_id = None
        with self.assertRaisesRegex(ValueError, "browser session"):
            s.nodes.PickFromBatch().pick(s.images(), 0, mode="interactive", unique_id="7")


class StoreTests(unittest.TestCase):
    def setUp(self):
        s.reset()
        self.store = s.state.selections
        self.request = self.store.create("7", "prompt-1", "browser-a", [{}, {}, {}])

    def test_recovery_is_scoped_to_client(self):
        self.assertEqual(self.store.pending("browser-a"), [self.request.snapshot()])
        self.assertEqual(self.store.pending("browser-b"), [])
        with self.assertRaises(s.state.SelectionError) as error:
            self.store.resolve(self.request.request_id, "browser-b", "stop")
        self.assertEqual(error.exception.status, 403)
        self.assertFalse(self.request.event.is_set())

    def test_invalid_choices_do_not_resume(self):
        for index in [-1, 3, True, "1", None, 1.5]:
            with self.assertRaises(s.state.SelectionError):
                self.store.resolve(self.request.request_id, "browser-a", "pick", index)
            self.assertFalse(self.request.event.is_set())

    def test_duplicate_stale_and_same_node_new_request(self):
        token = self.request.request_id
        self.store.resolve(token, "browser-a", "pick", 2)
        self.assertEqual(self.store.pending("browser-a"), [])
        with self.assertRaises(s.state.SelectionError) as error:
            self.store.resolve(token, "browser-a", "stop")
        self.assertEqual(error.exception.status, 409)
        self.store.remove(token)
        next_request = self.store.create("7", "prompt-2", "browser-a", [{}])
        self.assertNotEqual(token, next_request.request_id)
        with self.assertRaises(s.state.SelectionError) as error:
            self.store.resolve(token, "browser-a", "pick", 0)
        self.assertEqual(error.exception.status, 404)
        self.assertFalse(next_request.event.is_set())


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        s.reset()
        app = web.Application()
        app.add_routes(s.server.routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.request = s.state.selections.create("7", "prompt-1", "browser-a", [{}, {}])

    async def asyncTearDown(self):
        await self.client.close()

    async def test_recovery_and_response_http(self):
        response = await self.client.get("/phluffhead/pick/pending?client_id=browser-a")
        self.assertEqual((await response.json())["pending"], [self.request.snapshot()])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = await self.client.post("/phluffhead/pick/respond", json={
            "request_id": self.request.request_id, "client_id": "browser-a", "action": "pick", "index": 1,
        })
        self.assertEqual(response.status, 200)
        self.assertTrue(self.request.event.is_set())
        self.assertEqual(self.request.index, 1)

    async def test_malformed_requests_do_not_resume(self):
        for body in ["not json", "[]", '{}', '{"request_id":[],"client_id":"a"}']:
            response = await self.client.post("/phluffhead/pick/respond", data=body, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status, 400)
        self.assertFalse(self.request.event.is_set())
