"""Offline packaging, syntax isolation and third-party provenance checks."""
import ast
import hashlib
import json
from pathlib import Path
import re
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'bomberstudio_blender'
VENDOR = ADDON / 'vendor/io_scene_valvesource'


def literal(path, name):
    for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('Missing literal: ' + name)


class ReleaseLayoutTests(unittest.TestCase):
    def test_core_keeps_python35_syntax(self):
        paths = list(ADDON.glob('*.py')) + [ADDON / 'vendor/__init__.py']
        for path in paths:
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding='utf-8-sig'), feature_version=(3, 5))

    def test_version_contracts(self):
        version = literal(ADDON / 'core.py', 'VERSION')
        self.assertEqual(literal(ADDON / '__init__.py', 'bl_info')['version'], version)
        manifest = (ADDON / 'blender_manifest.toml').read_text(encoding='utf8')
        self.assertEqual(re.search(r'^version = "([^"]+)"', manifest, re.M).group(1),
                         '.'.join(map(str, version)))
        metadata = literal(VENDOR / '__init__.py', 'bl_info')
        self.assertEqual(metadata['blender'], literal(ADDON / 'source_tools.py', 'MIN_VERSION'))
        self.assertEqual(metadata['version'], literal(ADDON / 'source_tools.py', 'SOURCE_VERSION'))

    def test_extension_permission_descriptions_fit_schema(self):
        manifest = (ADDON / 'blender_manifest.toml').read_text(encoding='utf8')
        permissions = manifest.split('[permissions]', 1)[1].split('\n[', 1)[0]
        values = re.findall(r'^\w+\s*=\s*"([^"]+)"\s*$', permissions, re.M)
        self.assertTrue(values)
        for description in values:
            self.assertGreater(len(description), 0)
            self.assertLessEqual(len(description), 64)

    def test_original_notices_and_provenance(self):
        record = json.loads((VENDOR / 'PROVENANCE.json').read_text(encoding='utf8'))
        self.assertEqual(len(record['original_sha256']), 10)
        for name, digest in record['original_sha256'].items():
            if name not in record['modified_files']:
                self.assertEqual(hashlib.sha256((VENDOR / name).read_bytes()).hexdigest(), digest, name)
        self.assertIn('GNU GENERAL PUBLIC LICENSE', (VENDOR / 'LICENSE.txt').read_text(encoding='utf8'))
        self.assertIn('Luminoso Technologies', (VENDOR / 'LICENSE-ordered-set.txt').read_text(encoding='utf8'))
        self.assertIn('The MIT License', (VENDOR / 'datamodel.py').read_text(encoding='utf-8-sig'))

    def test_vendor_only_loaded_lazily(self):
        source = (ADDON / 'source_tools.py').read_text(encoding='utf8')
        module = ast.parse(source)
        for node in module.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.assertNotIn('io_scene_valvesource', ast.unparse(node))
        self.assertIn("importlib.import_module('.vendor.io_scene_valvesource', __package__)", source)
        self.assertNotIn('urlopen', (VENDOR / 'update.py').read_text(encoding='utf8'))
        self.assertNotIn('extractall', (VENDOR / 'update.py').read_text(encoding='utf8'))

    def test_published_zip_matches_source(self):
        release = json.loads((ROOT / 'release-manifest.json').read_text(encoding='utf8'))
        package = release['packages'][0]
        archive = ROOT / package['file']
        if not archive.exists():
            self.skipTest('Run tools/build_release.py to produce the release ZIP')
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), package['sha256'])
        with zipfile.ZipFile(archive) as zipped:
            self.assertIsNone(zipped.testzip())
            for path in ADDON.rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.md', '.json', '.txt', '.toml'):
                    name = 'bomberstudio_blender/' + path.relative_to(ADDON).as_posix()
                    self.assertEqual(zipped.read(name), path.read_bytes(), name)
            self.assertFalse(any('__pycache__' in name or name.endswith(('.pyc', '.zip')) for name in zipped.namelist()))


if __name__ == '__main__':
    unittest.main()
