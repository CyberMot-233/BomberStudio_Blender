"""Run public update operators against an isolated installed ZIP; Python 3.5 syntax."""
import ast
import hashlib
import importlib
import io
import json
import os
import re
import types
import zipfile
import bpy


def candidate_zip(archive, version):
    result = io.BytesIO()
    text_version = '.'.join(str(v) for v in version)
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as dest:
        for name in source.namelist():
            payload = source.read(name)
            if name == 'bomberstudio_blender/__init__.py':
                text = payload.decode('utf8')
                text = re.sub(r"('version':\s*)\([0-9, ]+\)", lambda m: m.group(1) + repr(tuple(version)), text, count=1)
                payload = text.encode('utf8')
            elif name == 'bomberstudio_blender/core.py':
                text = payload.decode('utf8')
                text = re.sub(r'(?m)^VERSION = .+$', 'VERSION = ' + repr(tuple(version)), text)
                payload = text.encode('utf8')
            elif name == 'bomberstudio_blender/blender_manifest.toml':
                text = payload.decode('utf8')
                payload = re.sub(r'(?m)^version = "[^"]+"', 'version = "' + text_version + '"', text).encode('utf8')
            dest.writestr(name, payload)
    return result.getvalue()


class Response(io.BytesIO):
    def __init__(self, payload, url):
        super().__init__(payload)
        self.url = url
        self.headers = {'Content-Length': str(len(payload))}

    def geturl(self):
        return self.url


class Layout:
    def __init__(self, rows):
        self.rows = rows
        self.enabled = True
        self.alert = False

    def column(self, *args, **kwargs):
        return Layout(self.rows)

    row = column
    box = column

    def label(self, text='', **kwargs):
        self.rows.append(('label', text, self.alert))

    def prop(self, *args, **kwargs):
        pass

    def operator(self, name, text='', **kwargs):
        self.rows.append(('operator', text or name, self.enabled))
        return types.SimpleNamespace()


def draw_labels(addon, context):
    rows = []
    addon.ui.BOMBER_PT_updates.draw(types.SimpleNamespace(layout=Layout(rows)), context)
    return rows


def run(addon, archive, out):
    os.makedirs(out, exist_ok=True)
    core = addon.core
    online = addon.online_update
    updates = importlib.import_module(addon.__name__ + '.updates')
    cfg = bpy.context.scene.bomberstudio
    original_cfg = (cfg.temp_dir, cfg.update_repository, cfg.update_status, cfg.update_last_check)
    original_state = (online._record, online._restart, online._restart_message)
    old_open = updates.urllib.request.urlopen
    old_builder = updates.urllib.request.build_opener
    system = getattr(getattr(bpy.context, 'preferences', None), 'system', None)
    access = getattr(system, 'use_online_access', None)
    original_version = tuple(core.VERSION)
    new_version = (original_version[0], original_version[1], original_version[2] + 1)
    target = os.path.dirname(addon.__file__)
    assert os.path.commonpath([os.path.realpath(out), os.path.realpath(target)]) != os.path.realpath(target)
    target_core = os.path.join(target, 'core.py')
    original_hash = core.sha256(target_core)
    payload = candidate_zip(archive, new_version)
    text_version = '.'.join(str(v) for v in new_version)
    tag = 'v' + text_version
    name = 'BomberStudio_Blender_' + text_version + '_Universal.zip'
    url = 'https://github.com/' + updates.DEFAULT_REPOSITORY + '/releases/download/' + tag + '/' + name
    asset = {'id': 123, 'name': name, 'size': len(payload),
             'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(), 'browser_download_url': url}
    release = {'tag_name': tag, 'assets': [asset]}
    rows, downloads = [], []

    def check(request, **kwargs):
        return Response(json.dumps(release).encode('utf8'), request.full_url)

    def download(request, **kwargs):
        assert kwargs.get('timeout') == 15
        assert request.full_url == url
        downloads.append(request.full_url)
        return Response(payload, url)

    def success(name):
        rows.append({'name': name, 'passed': True})

    def expect_failure(operator, contains):
        try:
            result = operator()
            assert result == {'CANCELLED'}
        except RuntimeError as exc:
            assert contains in str(exc), str(exc)
        assert contains in cfg.update_status or contains in ('重新检查',)
        assert core.sha256(target_core) == original_hash

    try:
        online._record, online._restart = None, False
        cfg.temp_dir = out
        cfg.update_repository = updates.DEFAULT_REPOSITORY
        if access is not None:
            system.use_online_access = True
        updates.urllib.request.urlopen = check
        updates.urllib.request.build_opener = lambda *args: types.SimpleNamespace(open=download)

        cleaned = []
        online.BOMBER_OT_online_update.cancel(types.SimpleNamespace(_cleanup=lambda: cleaned.append(True)), bpy.context)
        assert cleaned == [True]
        success('cancel_confirmation_before_worker_is_created')

        assert any('手动检查更新' in r[1] for r in draw_labels(addon, bpy.context))
        success('idle_check_button')
        assert bpy.ops.bomberstudio.online_update(action='CHECK') == {'FINISHED'}
        assert online.can_install(bpy.context)
        assert any('立即更新至 ' + text_version in r[1] and r[2] for r in draw_labels(addon, bpy.context))
        success('new_version_enables_install_button')
        assert not downloads
        success('manual_check_does_not_download')
        cfg.update_repository = 'other/repo'
        assert not online.can_install(bpy.context)
        cfg.update_repository = updates.DEFAULT_REPOSITORY
        success('changed_repository_invalidates_target')
        online._record['checked_epoch'] = 0
        assert not online.can_install(bpy.context)
        assert bpy.ops.bomberstudio.online_update(action='CHECK') == {'FINISHED'}
        success('stale_check_requires_refresh')

        asset['digest'] = 'sha256:' + '0' * 64
        assert bpy.ops.bomberstudio.online_update(action='CHECK') == {'FINISHED'}
        expect_failure(lambda: bpy.ops.bomberstudio.online_update(action='INSTALL'), 'SHA256')
        success('hash_failure_leaves_installed_files_unchanged')
        asset['digest'] = 'sha256:' + hashlib.sha256(payload).hexdigest()
        assert bpy.ops.bomberstudio.online_update(action='CHECK') == {'FINISHED'}
        assert bpy.ops.bomberstudio.online_update(action='INSTALL') == {'FINISHED'}
        receipt = core.read_json(os.path.join(out, 'last-update.json'))
        assert receipt['phase'] == 'installed' and receipt['installed_version'] == list(new_version)
        assert receipt['sha256'] == hashlib.sha256(payload).hexdigest()
        assert core.sha256(os.path.join(receipt['backup'], 'core.py')) == original_hash
        with open(target_core, encoding='utf8') as stream:
            written = next(ast.literal_eval(n.value) for n in ast.parse(stream.read()).body
                           if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', None) == 'VERSION')
        assert written == new_version and tuple(core.VERSION) == original_version
        success('operator_download_validate_backup_and_install')
        assert online.restart_required() and not online.can_install(bpy.context)
        ui = draw_labels(addon, bpy.context)
        assert any('请保存工作并重启 Blender 完成更新' in r[1] and r[2] for r in ui)
        assert not any('立即更新至' in r[1] for r in ui)
        success('red_restart_banner_and_no_hot_reload')
        assert bpy.ops.bomberstudio.manage(action='RESTORE_UPDATE') == {'FINISHED'}
        assert core.sha256(target_core) == original_hash
        success('one_click_rollback_restores_original')

        # A same-process test reset simulates the clean session after a restart.
        online._restart = False
        release['assets'] = []
        assert bpy.ops.bomberstudio.online_update(action='CHECK') == {'FINISHED'}
        assert not online.can_install(bpy.context)
        success('no_asset_disables_install')

        online._active = types.SimpleNamespace(_job=types.SimpleNamespace(snapshot=lambda: {
            'phase': 'DOWNLOADING', 'progress': 0.5, 'received': 1024, 'total': 2048}))
        ui = draw_labels(addon, bpy.context)
        assert any('取消' in r[1] for r in ui) and any('进度' in r[1] for r in ui)
        online._active = None
        success('download_progress_and_cancel_layout')
        result = {'passed': True, 'checks': rows, 'installed_target': target,
                  'archive': archive, 'candidate_version': list(new_version),
                  'original_version': list(original_version), 'source_restored': True,
                  'download_calls': len(downloads), 'network': 'in-memory HTTPS responses'}
        core.atomic_json(os.path.join(out, 'online-install-results.json'), result, backup=False)
        return result
    finally:
        updates.urllib.request.urlopen = old_open
        updates.urllib.request.build_opener = old_builder
        online._active = None
        online._record, online._restart, online._restart_message = original_state
        if access is not None:
            system.use_online_access = access
        cfg = bpy.context.scene.bomberstudio
        cfg.temp_dir, cfg.update_repository, cfg.update_status, cfg.update_last_check = original_cfg
