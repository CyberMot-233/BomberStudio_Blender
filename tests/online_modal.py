"""Hidden GUI Blender 4.5 test: real modal events/threads, mocked HTTPS bodies, isolated profile."""
import ast
import hashlib
import importlib
import json
import os
import subprocess
import sys
import threading
import time
import types
import traceback
import bpy

archive, out = sys.argv[sys.argv.index('--') + 1:]
os.makedirs(out, exist_ok=True)
sys.path.insert(0, os.path.dirname(__file__))
from online_install_integration import Response, candidate_zip

MAIN_THREAD = threading.get_ident()
workers = set()
pulses = 0
phase = 'INIT'
started = time.monotonic()
rows = []
addon = None
old_open = None
old_builder = None
original_hash = None
target_core = None
payload = None
cancel_at = 0


def finish(passed, error=''):
    if addon is not None:
        addon.online_update.shutdown()
        if old_open:
            addon.online_update.updates.urllib.request.urlopen = old_open
            addon.online_update.updates.urllib.request.build_opener = old_builder
    result = {'passed': passed, 'checks': rows, 'error': error, 'pulses': pulses,
              'worker_ids': sorted(workers), 'main_thread': MAIN_THREAD,
              'profile': out, 'blender': bpy.app.version_string,
              'network': 'mocked HTTPS response; real worker and modal event loop'}
    with open(os.path.join(out, 'modal-result.json'), 'w', encoding='utf8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print('ONLINE_MODAL_RESULT', json.dumps(result, ensure_ascii=False), flush=True)
    bpy.ops.wm.quit_blender()


def init():
    global addon, old_open, old_builder, payload, original_hash, target_core
    directory = os.path.join(out, 'extension-repo')
    os.makedirs(directory, exist_ok=True)
    repo = bpy.context.preferences.extensions.repos.new(
        name='BomberStudio Modal Test', module='bomber_gui', custom_directory=directory)
    repo.use_custom_directory = True
    repo.use_remote_url = False
    repo.enabled = True
    bpy.context.preferences.system.use_online_access = True
    assert bpy.ops.extensions.package_install_files(
        filepath=archive, repo=repo.module, enable_on_install=True) == {'FINISHED'}
    addon = importlib.import_module('bl_ext.bomber_gui.bomberstudio_blender')
    cfg = bpy.context.scene.bomberstudio
    cfg.temp_dir = os.path.join(out, 'temp')
    os.makedirs(cfg.temp_dir, exist_ok=True)
    cfg.update_repository = addon.online_update.updates.DEFAULT_REPOSITORY
    new = (addon.core.VERSION[0], addon.core.VERSION[1], addon.core.VERSION[2] + 1)
    ver = '.'.join(str(v) for v in new)
    tag = 'v' + ver
    name = 'BomberStudio_Blender_' + ver + '_Universal.zip'
    url = 'https://github.com/' + cfg.update_repository + '/releases/download/' + tag + '/' + name
    payload = candidate_zip(archive, new)
    release = {'tag_name': tag, 'assets': [{'id': 1, 'name': name, 'size': len(payload),
                'digest': 'sha256:' + hashlib.sha256(payload).hexdigest(), 'browser_download_url': url}]}
    target_core = os.path.join(os.path.dirname(addon.__file__), 'core.py')
    original_hash = addon.core.sha256(target_core)

    def check(request, **kwargs):
        workers.add(threading.get_ident())
        assert threading.get_ident() != MAIN_THREAD
        time.sleep(0.25)
        return Response(json.dumps(release).encode('utf8'), request.full_url)

    class SlowResponse(Response):
        def read(self, size=-1):
            time.sleep(0.15)
            return super().read(size)

    def download(request, **kwargs):
        workers.add(threading.get_ident())
        assert threading.get_ident() != MAIN_THREAD
        return SlowResponse(payload, url)

    u = addon.online_update.updates
    old_open, old_builder = u.urllib.request.urlopen, u.urllib.request.build_opener
    u.urllib.request.urlopen = check
    u.urllib.request.build_opener = lambda *args: types.SimpleNamespace(open=download)


def invoke(action):
    window = bpy.context.window_manager.windows[0]
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    with bpy.context.temp_override(window=window, area=area):
        return bpy.ops.bomberstudio.online_update(action=action)


def tick():
    global phase, pulses, cancel_at
    pulses += 1
    try:
        if time.monotonic() - started > 45:
            raise AssertionError('GUI modal test timed out in ' + phase)
        if phase == 'INIT':
            init()
            assert invoke('CHECK') == {'RUNNING_MODAL'}
            phase = 'CHECK'
        elif phase == 'CHECK' and not addon.online_update.is_busy():
            assert addon.online_update.can_install(bpy.context)
            rows.append({'name': 'nonblocking_check_worker_and_main_thread_completion', 'passed': True})
            assert invoke('INSTALL') == {'RUNNING_MODAL'}
            cancel_at = time.monotonic() + 0.07
            phase = 'CANCEL'
        elif phase == 'CANCEL' and time.monotonic() > cancel_at:
            assert bpy.ops.bomberstudio.cancel_online_update() == {'FINISHED'}
            phase = 'CANCEL_WAIT'
        elif phase == 'CANCEL_WAIT' and not addon.online_update.is_busy():
            assert addon.core.sha256(target_core) == original_hash
            assert not addon.online_update.restart_required()
            rows.append({'name': 'modal_cancel_keeps_installation', 'passed': True})
            assert invoke('INSTALL') == {'RUNNING_MODAL'}
            phase = 'INSTALL'
        elif phase == 'INSTALL' and not addon.online_update.is_busy():
            assert addon.online_update.restart_required(), bpy.context.scene.bomberstudio.update_status
            assert addon.core.sha256(target_core) != original_hash
            rows.append({'name': 'modal_retry_installs_and_requests_restart', 'passed': True})
            cold = os.path.join(out, 'cold')
            os.makedirs(cold, exist_ok=True)
            new_version = '.'.join(str(v) for v in (
                addon.core.VERSION[0], addon.core.VERSION[1], addon.core.VERSION[2] + 1))
            env = dict(os.environ, BLENDER_USER_CONFIG=os.path.join(cold, 'config'),
                       BLENDER_USER_SCRIPTS=os.path.join(cold, 'scripts'),
                       BLENDER_USER_EXTENSIONS=os.path.join(cold, 'extensions'))
            result_path = os.path.join(cold, 'result.json')
            with open(os.path.join(cold, 'process.log'), 'w', encoding='utf8') as log:
                child = subprocess.run([
                    bpy.app.binary_path, '--background', '--factory-startup', '--threads', '2',
                    '--python-exit-code', '1', '--python', os.path.join(os.path.dirname(__file__), 'online_restart.py'),
                    '--', os.path.join(out, 'extension-repo'), new_version, result_path],
                    env=env, stdout=log, stderr=subprocess.STDOUT, timeout=20,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert child.returncode == 0
            with open(result_path, encoding='utf8') as stream:
                assert json.load(stream)['passed']
            rows.append({'name': 'fresh_blender_process_loads_new_version', 'passed': True})
            assert bpy.ops.bomberstudio.manage(action='RESTORE_UPDATE') == {'FINISHED'}
            assert addon.core.sha256(target_core) == original_hash
            rows.append({'name': 'gui_rollback_restores_source', 'passed': True})
            assert pulses > 5 and workers and MAIN_THREAD not in workers
            rows.append({'name': 'main_thread_remains_responsive', 'passed': True})
            finish(True)
            return None
    except Exception:
        finish(False, traceback.format_exc())
        return None
    return 0.03


bpy.app.timers.register(tick, first_interval=0.5)
