import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import support as s

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup', ROOT / 'scripts/setup_runpod_portrait.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PortraitTests(unittest.TestCase):
    def test_release_preserves_pixels_and_honors_cancel(self):
        s.reset()
        batch = s.images()
        with patch.object(s.model_management, 'unload_all_models', create=True) as unload, patch.object(s.model_management, 'soft_empty_cache', create=True) as clear:
            self.assertIs(s.nodes.ReleaseModels().release(batch)[0], batch)
            unload.assert_called_once()
            clear.assert_called_once()
            s.interrupted.set()
            with self.assertRaises(s.InterruptProcessingException):
                s.nodes.ReleaseModels().release(batch)
            unload.assert_called_once()

    def test_graph_links_and_selection_gate(self):
        graph = json.loads((ROOT / 'examples' / setup.WORKFLOW).read_text())
        nodes = {n['id']: n for n in graph['nodes']}
        incoming = {i: [] for i in nodes}
        for link, src, slot, dst, port, typ in graph['links']:
            self.assertIn(link, nodes[src]['outputs'][slot]['links'])
            self.assertEqual(nodes[dst]['inputs'][port]['link'], link)
            incoming[dst].append(src)
        def ancestors(node, trail=()):
            self.assertNotIn(node, trail, 'Graph cycle')
            result = set(incoming[node])
            for parent in incoming[node]:
                result.update(ancestors(parent, trail + (node,)))
            return result
        picker = next(n['id'] for n in nodes.values() if n['type'] == 'Phluffhead_PickFromBatch')
        upscale = next(n for n in nodes.values() if n['type'] == 'SeedVR2VideoUpscaler')
        self.assertIn(picker, ancestors(upscale['id']))
        self.assertEqual(sum(n['type'] == 'KSampler' for n in nodes.values()), 2)
        for node in nodes:
            ancestors(node)

    def test_install_backs_up_and_retains_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / 'custom_nodes' / 'Phluffhead_Custom_Nodes'
            package.mkdir(parents=True)
            (package / 'nodes.py').write_text('class PickFromBatch: pass\n')
            (package / '__init__.py').write_text('# Phluffhead_PickFromBatch\n')
            (package / 'keep.txt').write_text('retain')
            self.assertEqual(setup.find_package(root), package)
            backup = setup.install_package(root, package)
            self.assertEqual((backup / 'nodes.py').read_text(), 'class PickFromBatch: pass\n')
            self.assertEqual((package / 'keep.txt').read_text(), 'retain')
            self.assertTrue((package / 'web/pick_from_batch.js').is_file())
            self.assertEqual((package / 'nodes.py').read_bytes(), (ROOT / 'Phluffhead_Custom_Nodes/nodes.py').read_bytes())
