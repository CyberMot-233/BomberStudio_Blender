"""Cold-load a just-updated native Extension in a separate isolated Blender process."""
import addon_utils
import bpy
import importlib
import json
import os
import sys

directory, expected, output = sys.argv[sys.argv.index('--') + 1:]
repo = bpy.context.preferences.extensions.repos.new(
    name='BomberStudio Cold Restart Test', module='bomber_restart', custom_directory=directory)
repo.use_custom_directory = True
repo.use_remote_url = False
repo.enabled = True
bpy.utils.refresh_script_paths()
addon_utils.modules_refresh()
name = 'bl_ext.bomber_restart.bomberstudio_blender'
assert addon_utils.enable(name, default_set=False, persistent=False) is not None
addon = importlib.import_module(name)
actual = '.'.join(str(v) for v in addon.core.VERSION)
assert actual == expected, (actual, expected)
assert hasattr(bpy.types.Scene, 'bomberstudio')
assert not addon.online_update.restart_required()
result = {'passed': True, 'expected': expected, 'actual': actual, 'module': name,
          'module_path': addon.__file__, 'blender': bpy.app.version_string}
with open(output, 'w', encoding='utf8') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
addon_utils.disable(name, default_set=False)
print('COLD_RESTART_PASS', json.dumps(result, ensure_ascii=False), flush=True)
