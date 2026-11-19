"""Updater operator checks against an installed addon; Python 3.5 compatible."""
import importlib
import json
import os
import urllib.error
import bpy


class Response:
    def __init__(self, tag):
        self.payload = json.dumps({'tag_name': tag}).encode('utf8')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.payload[:size]


def run(addon, out, live=False):
    updates = importlib.import_module(addon.__name__ + '.updates')
    core = importlib.import_module(addon.__name__ + '.core')
    os.makedirs(out, exist_ok=True)
    cfg = bpy.context.scene.bomberstudio
    original_settings = (cfg.temp_dir, cfg.update_repository, cfg.update_status)
    cfg.temp_dir = out
    prefs = getattr(bpy.context, 'preferences', None)
    system = getattr(prefs, 'system', None)
    online_setting = getattr(system, 'use_online_access', None)
    opener = updates.urllib.request.urlopen
    calls = []
    rows = []
    live_record = None
    tag = ['BomberStudio_Blender_' + '.'.join(str(v) for v in core.VERSION)]

    def fake(request, timeout):
        calls.append({'url': request.full_url, 'timeout': timeout})
        return Response(tag[0])

    def success(name):
        rows.append({'name': name, 'passed': True})

    try:
        if online_setting is not None:
            system.use_online_access = True
        assert cfg.update_repository == updates.DEFAULT_REPOSITORY
        success('default_repository')
        updates.urllib.request.urlopen = fake
        values = (
            ('full_url', 'https://github.com/' + updates.DEFAULT_REPOSITORY, updates.DEFAULT_REPOSITORY),
            ('shorthand', updates.DEFAULT_REPOSITORY, updates.DEFAULT_REPOSITORY),
            ('empty_saved_setting', '', updates.DEFAULT_REPOSITORY),
            ('custom_repository', 'https://github.com/Test-Owner/custom-plugin.git', 'Test-Owner/custom-plugin'),
        )
        for name, value, expected in values:
            cfg.update_repository = value
            assert bpy.ops.bomberstudio.manage(action='CHECK_UPDATE') == {'FINISHED'}
            record = core.read_json(os.path.join(out, 'last-update-check.json'))
            assert record['repository'] == expected
            assert record['relation'] == 'CURRENT'
            assert calls[-1]['url'] == 'https://api.github.com/repos/' + expected + '/releases/latest'
            assert calls[-1]['timeout'] == 15
            assert cfg.update_repository == (value or expected)
            success(name)

        cfg.update_repository = updates.DEFAULT_REPOSITORY
        for name, next_tag, relation in (
                ('new_release', 'v99.0.0', 'NEWER'),
                ('local_ahead', 'BomberStudio_Blender_0.0.1', 'OLDER'),
                ('unknown_version', 'nightly', 'UNKNOWN')):
            tag[0] = next_tag
            assert bpy.ops.bomberstudio.manage(action='CHECK_UPDATE') == {'FINISHED'}
            assert core.read_json(os.path.join(out, 'last-update-check.json'))['relation'] == relation
            success(name)

        def missing_release(*args, **kwargs):
            raise urllib.error.HTTPError('https://api.github.com/', 404, '', {}, None)

        previous = core.read_json(os.path.join(out, 'last-update-check.json'))
        updates.urllib.request.urlopen = missing_release
        try:
            result = bpy.ops.bomberstudio.manage(action='CHECK_UPDATE')
            assert result == {'CANCELLED'}
        except RuntimeError as exc:
            assert 'HTTP 404' in str(exc)
        assert 'HTTP 404' in cfg.update_status
        assert core.read_json(os.path.join(out, 'last-update-check.json')) == previous
        success('404_keeps_last_success_receipt')

        if online_setting is not None:
            updates.urllib.request.urlopen = fake
            count = len(calls)
            system.use_online_access = False
            try:
                result = bpy.ops.bomberstudio.manage(action='CHECK_UPDATE')
                assert result == {'CANCELLED'}
            except RuntimeError as exc:
                assert '关闭了在线访问' in str(exc)
            assert '关闭了在线访问' in cfg.update_status and len(calls) == count
            system.use_online_access = True
            success('respects_blender_offline_mode')

        updates.urllib.request.urlopen = opener
        if live:
            cfg.update_repository = 'https://github.com/' + updates.DEFAULT_REPOSITORY
            assert bpy.ops.bomberstudio.manage(action='CHECK_UPDATE') == {'FINISHED'}
            live_record = core.read_json(os.path.join(out, 'last-update-check.json'))
            assert live_record['repository'] == updates.DEFAULT_REPOSITORY
            assert live_record['repository_input'] == cfg.update_repository
            assert live_record['current_version'] == list(core.VERSION)
            assert live_record['tag']
            success('live_github_full_url_check')
    finally:
        updates.urllib.request.urlopen = opener
        if online_setting is not None:
            system.use_online_access = online_setting
        cfg.temp_dir, cfg.update_repository, cfg.update_status = original_settings
    result = {'passed': True, 'checks': rows, 'live': live, 'live_record': live_record,
              'module': addon.__name__, 'module_path': addon.__file__,
              'blender': bpy.app.version_string}
    core.atomic_json(os.path.join(out, 'update-results.json'), result, backup=False)
    return result
