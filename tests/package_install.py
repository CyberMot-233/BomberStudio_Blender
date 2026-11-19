"""Install the actual ZIP in an isolated Blender profile and exercise an operator."""
import bpy
import addon_utils
import importlib
import json
import os
import sys

args = sys.argv[sys.argv.index('--')+1:]
archive, kind, out = args
out = os.path.realpath(out)
os.makedirs(out, exist_ok=True)
if bpy.app.version < (2, 80, 0):
    scripts = os.path.realpath(os.path.join(out, 'scripts'))
    bpy.context.user_preferences.filepaths.script_directory = scripts
else:
    scripts = os.path.realpath(bpy.utils.user_resource('SCRIPTS'))
assert os.path.commonpath([out, scripts]) == out, ('Refusing non-isolated test profile', scripts, out)

if kind != 'Extension':
    if bpy.app.version < (2, 80, 0):
        result = bpy.ops.wm.addon_install(filepath=archive, overwrite=True, target='PREFS')
    else:
        result = bpy.ops.preferences.addon_install(filepath=archive, overwrite=True)
    assert result == {'FINISHED'}
    bpy.utils.refresh_script_paths()
    addon_utils.modules_refresh()
    module_name = 'bomberstudio_blender'
    addon_utils.enable(module_name, default_set=False, persistent=False)
else:
    directory = os.path.join(out, 'extension-repo')
    os.makedirs(directory, exist_ok=True)
    repo = bpy.context.preferences.extensions.repos.new(
        name='BomberStudio Isolated Installation Test', module='bomber_test', custom_directory=directory)
    repo.use_custom_directory = True
    repo.use_remote_url = False
    repo.enabled = True
    assert os.path.commonpath([out, os.path.realpath(repo.directory)]) == out
    result = bpy.ops.extensions.package_install_files(
        filepath=archive, repo=repo.module, enable_on_install=True)
    assert result == {'FINISHED'}, result
    module_name = 'bl_ext.' + repo.module + '.bomberstudio_blender'

addon = importlib.import_module(module_name)
from importlib import import_module
ascii_fbx = import_module(module_name + '.ascii_fbx')
version_module = import_module(module_name + '.core')
assert version_module.VERSION == (1, 0, 1), version_module.VERSION
assert hasattr(bpy.types.Scene, 'bomberstudio')
cfg = bpy.context.scene.bomberstudio
cfg.temp_dir = out
bpy.ops.mesh.primitive_cube_add()
assert bpy.ops.bomberstudio.model(action='NORMAL_UV') == {'FINISHED'}
assert 'Bomber_SmoothNormal_Oct' in bpy.context.object.data.uv_layers
ascii_source = os.path.join(out, 'ascii-install-check.fbx')
with open(ascii_source, 'wb') as stream:
    stream.write(b'FBXHeaderExtension:{FBXVersion:7700}\nObjects:{}\n')
converted, conversion = ascii_fbx.prepare_import(ascii_source, out)
assert conversion['converted'] and os.path.isfile(converted)
report = {'blender': bpy.app.version_string, 'kind': kind, 'module': module_name,
          'module_path': addon.__file__, 'archive': archive, 'passed': True,
          'addon_version': list(version_module.VERSION), 'ascii_conversion': True}
with open(os.path.join(out, 'installed.json'), 'w', encoding='utf8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
addon_utils.disable(module_name, default_set=False)
assert not hasattr(bpy.types.Scene, 'bomberstudio')
print('PACKAGE_INSTALL_PASS', json.dumps(report), flush=True)
