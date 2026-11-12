"""Synthetic archive tests. Do not upload real exam artifacts to public runners."""
from __future__ import annotations
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'unpack_artifact_tree.py'
spec = importlib.util.spec_from_file_location('unpack_artifact_tree', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def makezip(mapping):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for path, value in mapping.items():
            z.writestr(path, value)
    return out.getvalue()


class ArtifactTreeTest(unittest.TestCase):
    def test_nested_zip_unpacks_to_directories_with_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inner = makezip({'questions.json': '{}', 'media/question.png': b'abc'})
            p = root / 'artifact.zip'
            p.write_bytes(makezip({'result/report.txt': 'ok', 'package.zip': inner}))
            target = root / 'out'
            result = module.unpack(p, target)
            self.assertEqual(result['file_count'], 3)
            self.assertEqual(result['nested_archives_expanded'], 1)
            self.assertFalse((target / 'package.zip').exists())
            self.assertEqual((target / 'package' / 'questions.json').read_text(), '{}')
            self.assertEqual(json.loads((target / 'FILE-MANIFEST.json').read_text())['file_count'], 3)

    def test_reject_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'bad.zip'
            p.write_bytes(makezip({'../private.txt': 'escape'}))
            with self.assertRaises(ValueError):
                module.unpack(p, root / 'out')
            self.assertFalse((root / 'private.txt').exists())

    def test_reject_case_collision_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'collision.zip'
            p.write_bytes(makezip({'A/Question.json': 'one', 'a/question.json': 'two'}))
            with self.assertRaises(ValueError):
                module.unpack(p, root / 'out')
            self.assertFalse((root / 'out' / 'FILE-MANIFEST.json').exists())

    def test_budget_limit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'big.zip'
            p.write_bytes(makezip({'big.txt': '123456'}))
            with self.assertRaises(ValueError):
                module.unpack(p, root / 'out', max_bytes=3)

    def test_destination_must_be_empty(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / 'source.zip'
            p.write_bytes(makezip({'ok.txt': 'ok'}))
            out = root / 'out'
            out.mkdir()
            (out / 'existing.txt').write_text('keep')
            with self.assertRaises(ValueError):
                module.unpack(p, out)
            self.assertEqual((out / 'existing.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
