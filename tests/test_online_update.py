"""Offline network, archive and transaction regression tests (no bpy, no real writes to installations)."""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / '临时文件夹/online-unit-tests'
TMP.mkdir(parents=True, exist_ok=True)
package = types.ModuleType('bomber_online_fixture')
package.__path__ = [str(ROOT / 'bomberstudio_blender')]
sys.modules[package.__name__] = package
updates = importlib.import_module(package.__name__ + '.updates')
installer = importlib.import_module(package.__name__ + '.update_install')
jobs = importlib.import_module(package.__name__ + '.update_jobs')
core = importlib.import_module(package.__name__ + '.core')
REPO = updates.DEFAULT_REPOSITORY
TAG = 'v1.2.1'
NAME = 'BomberStudio_Blender_1.2.1_Universal.zip'
URL = 'https://github.com/' + REPO + '/releases/download/' + TAG + '/' + NAME


def content(version=(1, 2, 1)):
    return {
        '__init__.py': ("bl_info = " + repr({'name': 'BomberStudio Fixture', 'version': version,
                                           'blender': (2, 79, 0)}) + '\n').encode(),
        'core.py': ('VERSION = ' + repr(version) + '\n').encode(),
        'blender_manifest.toml': ('id = "bomberstudio_blender"\nversion = "' + '.'.join(map(str, version)) +
                                  '"\nblender_version_min = "4.2.0"\n').encode(),
    }


def zipped(values=None, prefix='bomberstudio_blender/'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (values or content()).items():
            archive.writestr(prefix + name, payload)
    return stream.getvalue()


def asset(payload, name=NAME):
    return {'id': 1, 'name': name, 'size': len(payload), 'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(),
            'browser_download_url': URL.rsplit('/', 1)[0] + '/' + name}


def record(payload):
    return {'repository': REPO, 'tag': TAG, 'remote_version': [1, 2, 1], 'relation': 'NEWER',
            'asset': updates.select_asset(REPO, TAG, (1, 2, 1), [asset(payload)])}


class Response(io.BytesIO):
    def __init__(self, payload, url=URL, declared=None):
        super().__init__(payload)
        self.url = url
        self.headers = {'Content-Length': str(len(payload) if declared is None else declared)}

    def geturl(self):
        return self.url


class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(TMP))
        self.root = Path(self.temp.name)
        assert TMP.resolve() in self.root.resolve().parents

    def tearDown(self):
        self.temp.cleanup()

    def zipfile(self, values=None, prefix='bomberstudio_blender/'):
        path = self.root / 'fixture.zip'
        path.write_bytes(zipped(values, prefix))
        return str(path)

    def installed(self):
        target = self.root / 'installed/bomberstudio_blender'
        target.mkdir(parents=True)
        for name, payload in content((1, 2, 0)).items():
            (target / name).write_bytes(payload)
        temp = self.root / 'temp'
        temp.mkdir()
        return str(target), str(temp)

    def test_asset_prefers_universal_over_generic(self):
        payload = zipped()
        generic = asset(payload, NAME.replace('_Universal', ''))
        result = updates.select_asset(REPO, TAG, (1, 2, 1), [generic, asset(payload)])
        self.assertEqual(result['name'], NAME)

    def test_generic_release_asset_supported(self):
        a = asset(zipped(), NAME.replace('_Universal', ''))
        self.assertEqual(updates.select_asset(REPO, TAG, (1, 2, 1), [a])['name'], a['name'])

    def test_repository_case_does_not_reject_github_canonical_asset_url(self):
        a = asset(zipped())
        self.assertEqual(updates.select_asset(REPO.lower(), TAG, (1, 2, 1), [a])['url'], URL)

    def test_source_code_and_unrelated_assets_not_selected(self):
        for name in ('Source code.zip', 'source.zip', 'other_plugin_1.2.1.zip', 'BomberStudio_Blender_9.0.0.zip'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                updates.select_asset(REPO, TAG, (1, 2, 1), [asset(zipped(), name)])

    def test_ambiguous_assets_rejected(self):
        a = asset(zipped())
        with self.assertRaisesRegex(ValueError, '多个'):
            updates.select_asset(REPO, TAG, (1, 2, 1), [a, a])

    def test_download_url_stays_in_checked_release(self):
        a = asset(zipped())
        for url in ('https://evil.invalid/asset.zip', URL.replace('/v1.2.1/', '/v1.2.0/'),
                    URL.replace(REPO, 'Other/Repo'), URL + '?token=abc'):
            a['browser_download_url'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                updates.select_asset(REPO, TAG, (1, 2, 1), [a])

    def test_hash_is_required(self):
        a = asset(zipped())
        a['digest'] = None
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            updates.select_asset(REPO, TAG, (1, 2, 1), [a])

    def test_asset_size_limit(self):
        a = asset(zipped())
        for size in (0, -1, True, 65 * 1024 * 1024):
            a['size'] = size
            with self.subTest(size=size), self.assertRaises(ValueError):
                updates.select_asset(REPO, TAG, (1, 2, 1), [a])

    def test_download_success_hash_size_and_progress(self):
        payload = zipped()
        progress = []
        result = updates.download_release(record(payload), str(self.root), (1, 2, 0),
            opener=lambda *a, **k: Response(payload), progress=lambda *v: progress.append(v))
        self.assertEqual(Path(result['path']).read_bytes(), payload)
        self.assertEqual(result['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(progress[-1], (len(payload), len(payload)))
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_checksum_file_fallback(self):
        payload = zipped()
        a = asset(payload)
        a['digest'] = None
        checksum = {'name': 'SHA256SUMS.txt', 'browser_download_url': URL.rsplit('/', 1)[0] + '/SHA256SUMS.txt'}
        r = record(payload)
        r['asset'] = updates.select_asset(REPO, TAG, (1, 2, 1), [a, checksum])
        def opener(request, **kwargs):
            if request.full_url.endswith('SHA256SUMS.txt'):
                return Response((hashlib.sha256(payload).hexdigest() + '  ' + NAME + '\n').encode(),
                                url=checksum['browser_download_url'])
            return Response(payload)
        result = updates.download_release(r, str(self.root), (1, 2, 0), opener=opener)
        self.assertEqual(result['verified_by'], 'release_SHA256SUMS')

    def test_corrupt_download_never_published(self):
        payload = zipped()
        r = record(payload)
        r['asset']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            updates.download_release(r, str(self.root), (1, 2, 0), opener=lambda *a, **k: Response(payload))
        self.assertFalse(list(self.root.rglob('*.zip')))
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_incomplete_download_removed(self):
        payload = zipped()
        with self.assertRaisesRegex(ValueError, '不完整'):
            updates.download_release(record(payload), str(self.root), (1, 2, 0),
                opener=lambda *a, **k: Response(payload[:-10], declared=len(payload)))
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_cancel_before_download_does_not_open_network(self):
        event = threading.Event()
        event.set()
        opener = mock.Mock()
        with self.assertRaises(updates.UpdateCancelled):
            updates.download_release(record(zipped()), str(self.root), (1, 2, 0), cancel=event, opener=opener)
        opener.assert_not_called()

    def test_cancel_during_download_cleans_partial(self):
        payload = zipped()
        event = threading.Event()
        with self.assertRaises(updates.UpdateCancelled):
            updates.download_release(record(payload), str(self.root), (1, 2, 0),
                cancel=event, progress=lambda *a: event.set(), opener=lambda *a, **k: Response(payload))
        self.assertFalse(list(self.root.rglob('*.part')))

    def test_redirect_outside_github_rejected(self):
        payload = zipped()
        with self.assertRaisesRegex(ValueError, '非 GitHub'):
            updates.download_release(record(payload), str(self.root), (1, 2, 0),
                opener=lambda *a, **k: Response(payload, url='http://localhost/asset'))

    def test_bad_redirect_blocked_before_request(self):
        handler = updates._GitHubRedirect()
        request = updates.urllib.request.Request(URL)
        with self.assertRaises(ValueError):
            handler.redirect_request(request, None, 302, '', {}, 'http://127.0.0.1/file')

    def test_zip_flat_and_wrapped_supported(self):
        for prefix in ('', 'bomberstudio_blender/'):
            values = installer.validate_addon_zip(self.zipfile(prefix=prefix), (4, 5, 5), (1, 2, 1), True)
            self.assertIn('__init__.py', values)

    def test_release_version_must_match_inside_zip(self):
        with self.assertRaisesRegex(ValueError, '内部版本'):
            installer.validate_addon_zip(self.zipfile(content((1, 1, 1))), (4, 5, 5), (1, 1, 2), True)

    def test_all_three_versions_must_match(self):
        values = content()
        values['core.py'] = b'VERSION = (0, 0, 0)\n'
        with self.assertRaisesRegex(ValueError, '版本不一致'):
            installer.validate_addon_zip(self.zipfile(values), (4, 5, 5))
        values = content()
        values['blender_manifest.toml'] = values['blender_manifest.toml'].replace(b'1.2.1', b'1.2.2')
        with self.assertRaisesRegex(ValueError, '版本与源码不一致'):
            installer.validate_addon_zip(self.zipfile(values), (4, 5, 5))

    def test_traversal_windows_streams_and_reserved_names(self):
        for name in ('../outside.py', 'a/../../outside.py', 'a:b.py', 'NUL.py', 'a./x.py', 'C:/x.py'):
            values = content()
            values[name] = b'# no execution'
            with self.subTest(name=name), self.assertRaises(ValueError):
                installer.validate_addon_zip(self.zipfile(values), (4, 5, 5))

    def test_case_collision_and_prefix_collision(self):
        for name in ('CORE.PY', 'core.py/extra.py'):
            values = content()
            values[name] = b'# no execution'
            with self.subTest(name=name), self.assertRaises(ValueError):
                installer.validate_addon_zip(self.zipfile(values), (4, 5, 5))

    def test_symlink_rejected(self):
        filename = self.zipfile()
        with zipfile.ZipFile(filename, 'a') as z:
            info = zipfile.ZipInfo('bomberstudio_blender/link')
            info.external_attr = 0o120777 << 16
            z.writestr(info, '../outside')
        with self.assertRaisesRegex(ValueError, '符号链接'):
            installer.validate_addon_zip(filename, (4, 5, 5))

    def test_bytecode_not_installed(self):
        values = content()
        values['__pycache__/core.cpython-311.pyc'] = b'junk'
        values['orphan.pyc'] = b'junk'
        actual = installer.validate_addon_zip(self.zipfile(values), (4, 5, 5))
        self.assertEqual(set(actual), set(content()))

    def test_new_syntax_and_modern_vendor_isolation(self):
        values = content()
        values['bad.py'] = b'not valid Python !'
        with self.assertRaises(SyntaxError):
            installer.validate_addon_zip(self.zipfile(values), (4, 5, 5))
        values = content()
        values['vendor/io_scene_valvesource/modern.py'] = b'not parsed by old runtime !'
        installer.validate_addon_zip(self.zipfile(values), (2, 79, 0))

    def test_extension_minimum_is_separate_from_legacy(self):
        filename = self.zipfile()
        installer.validate_addon_zip(filename, (2, 79, 0), extension=False)
        with self.assertRaisesRegex(ValueError, '更高版本'):
            installer.validate_addon_zip(filename, (4, 1, 0), extension=True)

    def test_online_install_requires_manifest(self):
        values = content()
        values.pop('blender_manifest.toml')
        filename = self.zipfile(values)
        installer.validate_addon_zip(filename, (2, 79, 0))
        with self.assertRaisesRegex(ValueError, '清单|manifest'):
            installer.validate_addon_zip(filename, (2, 79, 0), (1, 2, 1))

    def test_install_and_rollback_preserve_both_versions(self):
        target, temp = self.installed()
        filename = self.zipfile()
        r = installer.install_zip(filename, target, temp, (4, 5, 5),
                                  expected_version=(1, 2, 1), expected_sha256=core.sha256(filename))
        self.assertEqual(r['phase'], 'installed')
        self.assertEqual(Path(target, 'core.py').read_bytes(), content()['core.py'])
        self.assertEqual(Path(r['backup'], 'core.py').read_bytes(), content((1, 2, 0))['core.py'])
        restored = installer.restore(target, temp)
        self.assertEqual(restored['phase'], 'rolled_back')
        self.assertEqual(Path(target, 'core.py').read_bytes(), content((1, 2, 0))['core.py'])
        self.assertTrue(Path(restored['rollback_displaced'], 'core.py').is_file())
        with self.assertRaises(ValueError):
            installer.restore(target, temp)

    def test_hash_rechecked_immediately_before_install(self):
        target, temp = self.installed()
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            installer.install_zip(self.zipfile(), target, temp, (4, 5, 5), expected_sha256='0' * 64)
        self.assertEqual(Path(target, 'core.py').read_bytes(), content((1, 2, 0))['core.py'])

    def test_temp_inside_plugin_rejected(self):
        target, temp = self.installed()
        with self.assertRaisesRegex(ValueError, '安装目录之外'):
            installer.install_zip(self.zipfile(), target, str(Path(target) / 'temp'), (4, 5, 5))

    def test_cross_drive_temp_supported(self):
        target, temp = self.installed()
        with mock.patch.object(installer.os.path, 'commonpath', side_effect=ValueError('different drives')):
            self.assertEqual(installer._paths(target, temp), (os.path.realpath(target), os.path.realpath(temp)))

    def test_busy_lock_prevents_second_transaction(self):
        target, temp = self.installed()
        with installer._lock(os.path.realpath(target)):
            with self.assertRaisesRegex(ValueError, '事务正在运行'):
                installer.install_zip(self.zipfile(), target, temp, (4, 5, 5))

    def test_swap_failure_restores_original_and_receipt(self):
        target, temp = self.installed()
        receipt = Path(temp) / 'last-update.json'
        receipt.write_bytes(b'{"previous_operation": true}')
        replace = os.replace
        def fail_incoming(src, dst):
            if '.bomberstudio-incoming-' in str(src) and os.path.realpath(dst) == target:
                raise OSError('simulated locked destination')
            return replace(src, dst)
        with mock.patch.object(installer.os, 'replace', side_effect=fail_incoming):
            with self.assertRaises(OSError):
                installer.install_zip(self.zipfile(), target, temp, (4, 5, 5))
        self.assertEqual(Path(target, 'core.py').read_bytes(), content((1, 2, 0))['core.py'])
        self.assertEqual(receipt.read_bytes(), b'{"previous_operation": true}')

    def test_receipt_failure_after_commit_rolls_back_files(self):
        target, temp = self.installed()
        real = core.atomic_json
        def fail_receipt(path, value, **kwargs):
            if Path(path).name == 'last-update.json' and value.get('phase') == 'installed':
                raise OSError('simulated disk error')
            return real(path, value, **kwargs)
        with mock.patch.object(core, 'atomic_json', side_effect=fail_receipt):
            with self.assertRaises(OSError):
                installer.install_zip(self.zipfile(), target, temp, (4, 5, 5))
        self.assertEqual(Path(target, 'core.py').read_bytes(), content((1, 2, 0))['core.py'])
        self.assertFalse(Path(temp, 'last-update.json').exists())

    def test_backup_failure_leaves_target_untouched(self):
        target, temp = self.installed()
        with mock.patch.object(installer.shutil, 'copytree', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                installer.install_zip(self.zipfile(), target, temp, (4, 5, 5))
        self.assertEqual(Path(target, 'core.py').read_bytes(), content((1, 2, 0))['core.py'])

    def test_job_cancellation_has_no_blender_or_installation_effects(self):
        job = jobs.UpdateJob('CHECK', REPO, (1, 2, 0), str(self.root), (4, 5, 5))
        job.cancel()
        with mock.patch.object(jobs.updates, 'check_latest') as check:
            job.start()
            job.join(3)
            check.assert_not_called()
        self.assertTrue(job.snapshot()['cancelled'])

    def test_worker_stops_at_validated_download_not_install(self):
        payload = zipped()
        filename = self.zipfile()
        job = jobs.UpdateJob('INSTALL', REPO, (1, 2, 0), str(self.root), (4, 5, 5),
                             extension=True, record=record(payload))
        with mock.patch.object(jobs.updates, 'download_release', return_value={
                'path': filename, 'sha256': core.sha256(filename)}) as download:
            with mock.patch.object(jobs.update_install, 'install_zip') as commit:
                job.run()
                commit.assert_not_called()
        self.assertTrue(job.snapshot()['done'])
        self.assertFalse(job.snapshot()['error'])
        self.assertEqual(job.snapshot()['result']['metadata']['version'], [1, 2, 1])


if __name__ == '__main__':
    unittest.main()
