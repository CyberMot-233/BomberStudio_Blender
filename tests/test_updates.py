"""Pure-Python updater regression tests; no GitHub requests or bpy required."""
import importlib.util
import json
from pathlib import Path
import socket
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bomber_updates', str(ROOT / 'bomberstudio_blender/updates.py'))
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.payload[:size]


class UpdateTests(unittest.TestCase):
    def check(self, tag, version=(1, 1, 1)):
        payload = json.dumps({'tag_name': tag}).encode('utf8')
        return updates.check_latest(updates.DEFAULT_REPOSITORY, version,
                                    opener=lambda *args, **kwargs: Response(payload))

    def test_default_for_new_and_old_empty_settings(self):
        for value in ('', ' \t', None):
            self.assertEqual(updates.normalize_repository(value), updates.DEFAULT_REPOSITORY)

    def test_repository_and_complete_urls(self):
        for value in (
                'Hoshino486/BomberStudio_Blender',
                ' https://github.com/Hoshino486/BomberStudio_Blender ',
                'https://github.com/Hoshino486/BomberStudio_Blender/',
                'https://github.com/Hoshino486/BomberStudio_Blender.git',
                'Hoshino486/BomberStudio_Blender.git/',
                'github.com/Hoshino486/BomberStudio_Blender',
                'http://www.github.com/Hoshino486/BomberStudio_Blender',
                'https://github.com/Hoshino486/BomberStudio_Blender/releases/latest',
                'https://github.com/Hoshino486/BomberStudio_Blender/tree/main?tab=readme#about'):
            with self.subTest(value=value):
                self.assertEqual(updates.normalize_repository(value), updates.DEFAULT_REPOSITORY)

    def test_custom_repository_preserved(self):
        self.assertEqual(updates.normalize_repository('https://github.com/Another-Owner/custom.addon'),
                         'Another-Owner/custom.addon')

    def test_invalid_repository_or_host_rejected(self):
        for value in (
                'github.com/Hoshino486', 'owner', 'owner/repo/extra', 'owner/repo\njunk',
                'owner/..', 'owner/.', '../repo', 'https://github.com/owner//repo',
                'https://github.com/owner/../repo', 'https://gitlab.com/owner/repo',
                'https://github.com.evil.invalid/owner/repo', 'https://github.com@evil.invalid/owner/repo',
                'https://token@github.com/owner/repo', 'https://github.com:443/owner/repo',
                'file://github.com/owner/repo', 'owner/%2Frepo'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                updates.normalize_repository(value)

    def test_real_project_tag(self):
        self.assertEqual(updates.tag_version('BomberStudio_Blender_1.1.0'), (1, 1, 0))
        self.assertEqual(updates.tag_version('v1.1.1'), (1, 1, 1))
        self.assertEqual(updates.tag_version('1.10.2'), (1, 10, 2))
        self.assertIsNone(updates.tag_version('v1.1.2-beta'))
        self.assertIsNone(updates.tag_version('nightly'))

    def test_newer_release(self):
        result = self.check('BomberStudio_Blender_1.2.0')
        self.assertEqual(result['relation'], 'NEWER')
        self.assertIn('发现新版本', result['status'])

    def test_numeric_not_lexicographic_comparison(self):
        self.assertEqual(self.check('v1.10.0', (1, 9, 0))['relation'], 'NEWER')

    def test_equal_release(self):
        self.assertEqual(self.check('v1.1.1')['relation'], 'CURRENT')

    def test_older_release_not_offered_as_upgrade(self):
        result = self.check('BomberStudio_Blender_1.1.0')
        self.assertEqual(result['relation'], 'OLDER')
        self.assertIn('无需降级', result['status'])

    def test_unknown_version_is_not_claimed_current(self):
        self.assertEqual(self.check('nightly')['relation'], 'UNKNOWN')

    def test_request_uses_github_api_and_timeout(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return Response(b'{"tag_name": "v1.1.1"}')

        result = updates.check_latest('https://github.com/' + updates.DEFAULT_REPOSITORY,
                                      (1, 1, 1), opener=opener)
        request, timeout = calls[0]
        self.assertEqual(timeout, 15)
        self.assertEqual(request.full_url,
                         'https://api.github.com/repos/Hoshino486/BomberStudio_Blender/releases/latest')
        self.assertEqual(request.get_header('User-agent'), 'BomberStudio-Blender/1.1.1')
        self.assertEqual(result['release_url'],
                         'https://github.com/Hoshino486/BomberStudio_Blender/releases/latest')

    def test_response_size_bounded(self):
        def opener(*args, **kwargs):
            return Response(b' ' * (updates.MAX_RESPONSE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, '2 MiB'):
            updates.check_latest('', (1, 1, 1), opener=opener)

    def test_bad_responses(self):
        for payload in (b'not-json', b'\xff', b'[]', b'null', b'{}',
                        b'{"tag_name":123}', b'{"tag_name": ""}'):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                updates.check_latest('', (1, 1, 1),
                                     opener=lambda *args, **kwargs: Response(payload))

    def test_http_failures_are_distinguished(self):
        for code, headers, expected in ((404, {}, '正式 Release'), (403, {}, '拒绝访问'),
                                        (403, {'X-RateLimit-Remaining': '0'}, '频率受限'),
                                        (429, {}, '频率受限'), (502, {}, 'HTTP 502')):
            def opener(*args, **kwargs):
                raise urllib.error.HTTPError('https://api.github.com/', code, '', headers, None)
            with self.subTest(code=code, headers=headers), self.assertRaisesRegex(ValueError, expected):
                updates.check_latest('', (1, 1, 1), opener=opener)

    def test_network_timeout_and_dns_error(self):
        for error, expected in ((socket.timeout('timeout'), '超时'),
                                (urllib.error.URLError('DNS failure'), '连接 GitHub 失败')):
            def opener(*args, **kwargs):
                raise error
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, expected):
                updates.check_latest('', (1, 1, 1), opener=opener)

    def test_release_button_url_uses_custom_setting(self):
        self.assertEqual(updates.releases_url('https://github.com/owner/custom.git'),
                         'https://github.com/owner/custom/releases/latest')


if __name__ == '__main__':
    unittest.main()
