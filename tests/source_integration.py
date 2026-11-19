"""Actual Blender integration tests; portable fixtures, no game assets or SDK."""
import bpy
import importlib
import json
import os
import sys
import traceback


def run(addon, out, standalone_root=None):
    os.makedirs(out, exist_ok=True)
    provider = importlib.import_module(addon.__name__ + '.source_tools')
    C = importlib.import_module(addon.__name__ + '.compat')
    rows = []

    def check(name, callback):
        try:
            detail = callback()
            rows.append({'name': name, 'passed': True, 'detail': detail})
            print('SOURCE_PASS', name, detail, flush=True)
        except Exception:
            rows.append({'name': name, 'passed': False, 'error': traceback.format_exc()})
            print('SOURCE_FAIL', name, traceback.format_exc(), flush=True)
            raise

    def assert_true(value, message):
        assert value, message

    def paths_config():
        cfg = bpy.context.scene.bomberstudio
        cfg.temp_dir = out
        cfg.output_dir = os.path.join(out, 'output')
        cfg.backup_before_edit = False

    def clean():
        C.mode_object()
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete()
        paths_config()

    def cancelled(call):
        try:
            result = call()
        except RuntimeError:
            return True
        return result == {'CANCELLED'}

    try:
        if bpy.app.version < (4, 1, 0):
            check('old_blender_core_remains_available', lambda: assert_true(
                provider.status()[0] == 'UNSUPPORTED' and hasattr(bpy.types.Scene, 'bomberstudio'),
                provider.status()))
            check('modern_provider_never_imported', lambda: assert_true(
                not any(n.startswith(addon.__name__ + '.vendor.io_scene_valvesource') for n in sys.modules),
                'Modern vendor was imported on old Blender'))
            check('source_version_gate_reports_failure', lambda: assert_true(
                cancelled(lambda: bpy.ops.bomberstudio.source_tools(action='ENABLE')), 'No version gate'))
            return rows

        paths_config()
        check('bundled_provider_registered', lambda: assert_true(
            provider.status()[0] == 'BUNDLED', provider.status()))
        backend = provider.active_backend()
        check('updater_routes_to_parent', lambda: assert_true(
            'bomberstudio.manage' in open(backend.update.__file__, encoding='utf8').read(),
            'Standalone updater is still used'))

        def lifecycle():
            for index in range(3):
                provider.ensure_backend()
                state = provider.active_backend().State
                assert list(bpy.app.handlers.depsgraph_update_post).count(state._onDepsgraphUpdate) == 1
                assert list(bpy.app.handlers.load_post).count(state._onLoad) == 1
                assert bpy.ops.bomberstudio.source_tools(action='DISABLE') == {'FINISHED'}
                assert not hasattr(bpy.types.Scene, 'vs')
                assert not any(cls.is_registered for cls in backend._classes)
                for cls in backend.GUI.VERTEX_MAP_CLASSES:
                    assert not C.op_available(*cls.bl_idname.split('.'))
                assert state._onDepsgraphUpdate not in bpy.app.handlers.depsgraph_update_post
                assert state._onLoad not in bpy.app.handlers.load_post
                assert bpy.ops.bomberstudio.source_tools(action='ENABLE') == {'FINISHED'}
            return '3 enable/disable cycles; no leaked handlers, RNA classes or vertex-map operators'
        check('registration_lifecycle', lifecycle)

        triangle = os.path.join(out, 'triangle.smd')
        with open(triangle, 'w', encoding='ascii') as f:
            f.write('''version 1
nodes
0 "root" -1
end
skeleton
time 0
0 0 0 0 0 0 0
end
triangles
fixture_material
0 0 0 0 0 0 1 0 0 1 0 1
0 1 0 0 0 0 1 1 0 1 0 1
0 0 1 0 0 0 1 0 1 1 0 1
end
''')
        animation = os.path.join(out, 'idle.smd')
        with open(animation, 'w', encoding='ascii') as f:
            f.write('''version 1
nodes
0 "root" -1
end
skeleton
time 0
0 0 0 0 0 0 0
time 1
0 0.25 0 0 0 0 0
end
''')

        def smd_import():
            clean()
            assert bpy.ops.bomberstudio.import_source(filepath=triangle, bone_mode='NEW_ARMATURE') == {'FINISHED'}
            meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
            rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
            assert len(meshes) == 1 and len(rigs) == 1
            assert len(meshes[0].data.vertices) == 3 and len(meshes[0].data.polygons) == 1
            assert meshes[0].vertex_groups.get('root')
            assert abs(meshes[0].vertex_groups['root'].weight(0) - 1.0) < 1e-5
            assert meshes[0].data.uv_layers.active
            assert rigs[0].data.bones.get('root')
            C.select_only([meshes[0]]); C.set_active(meshes[0])
            for map_name in backend.vertex_maps:
                assert getattr(bpy.ops.smd, 'vertex_map_create_' + map_name)() == {'FINISHED'}
                assert map_name in meshes[0].data.vertex_colors
                assert getattr(bpy.ops.smd, 'vertex_map_remove_' + map_name)() == {'FINISHED'}
                assert map_name not in meshes[0].data.vertex_colors
            return 'Triangle, UV, material, root bone, weights, three vertex-map create/remove cycles'
        check('smd_mesh_rig_weights_import', smd_import)

        def animation_import():
            before = set(bpy.data.objects)
            assert bpy.ops.bomberstudio.import_source(filepath=animation, bone_mode='VALIDATE') == {'FINISHED'}
            rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
            assert rigs[0].animation_data and rigs[0].animation_data.action
            assert len([o for o in bpy.data.objects if o not in before and o.type == 'MESH']) == 0
            return 'Animation appended without requiring a new mesh'
        check('animation_import_existing_rig', animation_import)

        def export_smd_shapes():
            mesh = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
            if not mesh.data.shape_keys:
                mesh.shape_key_add(name='Basis')
            smile = mesh.shape_key_add(name='smile')
            smile.data[0].co.z += 0.25
            C.select_only([mesh])
            C.set_active(mesh)
            cfg = bpy.context.scene.vs
            cfg.export_path = os.path.join(out, 'smd-out')
            cfg.export_format = 'SMD'
            cfg.qc_compile = False
            provider.refresh_backend(bpy.context)
            assert bpy.ops.bomberstudio.export_source() == {'FINISHED'}
            files = [os.path.join(base, n) for base, dirs, names in os.walk(os.path.join(out, 'smd-out')) for n in names]
            smds = [p for p in files if p.endswith('.smd')]
            vtas = [p for p in files if p.endswith('.vta')]
            assert smds and vtas, files
            assert 'triangles' in open(smds[0], encoding='utf8').read()
            assert 'vertexanimation' in open(vtas[0], encoding='utf8').read()
            return {'smd': smds[0], 'vta': vtas[0]}
        check('smd_vta_export', export_smd_shapes)
        exported = rows[-1]['detail']

        def vta_import():
            clean()
            assert bpy.ops.bomberstudio.import_source(filepath=exported['smd'], bone_mode='NEW_ARMATURE') == {'FINISHED'}
            mesh = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
            C.select_only([mesh])
            C.set_active(mesh)
            assert bpy.ops.bomberstudio.import_source(filepath=exported['vta'], bone_mode='VALIDATE') == {'FINISHED'}
            mesh = bpy.data.objects[mesh.name]
            assert mesh.data.shape_keys and len(mesh.data.shape_keys.key_blocks) > 1
            keys = mesh.data.shape_keys.key_blocks
            assert any((key.data[i].co - keys[0].data[i].co).length > 0.01
                       for key in list(keys)[1:] for i in range(len(key.data)))
            return [key.name for key in keys]
        check('vta_shape_key_import', vta_import)

        def dmx_roundtrip():
            clean()
            assert bpy.ops.bomberstudio.import_source(filepath=triangle, bone_mode='NEW_ARMATURE') == {'FINISHED'}
            mesh = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
            mesh.shape_key_add(name='Basis')
            mesh.shape_key_add(name='smile').data[0].co.z += 0.3
            C.select_only([mesh]); C.set_active(mesh)
            cfg = bpy.context.scene.vs
            cfg.export_path = os.path.join(out, 'dmx-out')
            cfg.export_format = 'DMX'
            cfg.dmx_encoding = '5'
            cfg.dmx_format = '18'
            cfg.qc_compile = False
            provider.refresh_backend(bpy.context)
            assert bpy.ops.bomberstudio.export_source() == {'FINISHED'}
            files = [os.path.join(base, n) for base, dirs, names in os.walk(os.path.join(out, 'dmx-out')) for n in names if n.endswith('.dmx')]
            assert files
            clean()
            assert bpy.ops.bomberstudio.import_source(filepath=files[0], bone_mode='NEW_ARMATURE') == {'FINISHED'}
            meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
            rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
            assert meshes and rigs
            mesh = meshes[0]
            assert len(mesh.data.vertices) == 3 and len(mesh.data.polygons) == 1
            assert mesh.data.shape_keys and 'smile' in mesh.data.shape_keys.key_blocks
            assert abs(mesh.vertex_groups['root'].weight(0) - 1.0) < 1e-5
            return 'Binary DMX 5/model18: mesh, rig, weights, smile shape'
        check('dmx_binary_roundtrip', dmx_roundtrip)

        def qc_import():
            clean()
            qc = os.path.join(out, 'triangle.qc')
            qci = os.path.join(out, 'body.qci')
            with open(qci, 'w', encoding='ascii') as stream:
                stream.write('$body triangle "triangle.smd"\n')
            with open(qc, 'w', encoding='ascii') as stream:
                stream.write('$modelname "fixture.mdl"\n$include "body.qci"\n$sequence idle "idle.smd" fps 30\n')
            assert bpy.ops.bomberstudio.import_source(filepath=qc, bone_mode='NEW_ARMATURE') == {'FINISHED'}
            assert len([o for o in bpy.context.scene.objects if o.type == 'MESH']) == 1
            return 'QC + QCI + referenced SMD + idle animation; no external compiler invoked'
        check('qc_qci_import', qc_import)

        def bad_inputs():
            before = set(bpy.data.objects)
            assert cancelled(lambda: bpy.ops.bomberstudio.import_source(filepath=os.path.join(out, 'missing.smd')))
            assert before == set(bpy.data.objects)
            bpy.context.scene.vs.export_path = ''
            assert cancelled(lambda: bpy.ops.bomberstudio.export_source())
            previous = bpy.context.preferences.edit.use_enter_edit_mode
            bpy.context.preferences.edit.use_enter_edit_mode = True
            malformed = os.path.join(out, 'malformed.dmx')
            with open(malformed, 'w', encoding='ascii') as f:
                f.write('not a DMX file\n')
            try:
                assert cancelled(lambda: bpy.ops.bomberstudio.import_source(filepath=malformed))
                assert bpy.context.preferences.edit.use_enter_edit_mode is True
            finally:
                bpy.context.preferences.edit.use_enter_edit_mode = previous
            return 'Missing file, missing output directory, malformed DMX; preferences restored'
        check('error_paths', bad_inputs)

        def duplicate_registration_rollback():
            provider.unregister_backend()
            original = backend.import_smd.SmdImporter
            # This collision occurs near the end of registration, after most
            # classes have been registered, so it exercises rollback properly.
            # Blender may replace a class sharing only bl_idname, so register
            # an upstream class itself to cause a guaranteed registration error.
            bpy.utils.register_class(original)
            try:
                try:
                    backend.register()
                except (ValueError, RuntimeError):
                    pass
                else:
                    raise AssertionError('Duplicate registered class did not fail')
                assert not hasattr(bpy.types.Scene, 'vs')
                assert not backend._registered_classes
                assert original.is_registered
            finally:
                if original.is_registered:
                    bpy.utils.unregister_class(original)
                provider.ensure_backend()
            return 'Partial register failure rolls back only owned classes'
        check('partial_registration_rollback', duplicate_registration_rollback)

        if standalone_root:
            def coexistence():
                addon.unregister()
                sys.path.insert(0, standalone_root)
                original = os.path.join(standalone_root, 'io_scene_valvesource', '__init__.py')
                if os.path.isfile(original):
                    external = importlib.import_module('io_scene_valvesource')
                else:
                    # Public source tree: register a separately namespaced copy
                    # as the independent provider, without needing a second ZIP.
                    original = os.path.join(os.path.dirname(addon.__file__), 'vendor', 'io_scene_valvesource', '__init__.py')
                    spec = importlib.util.spec_from_file_location('io_scene_valvesource', original,
                                                                  submodule_search_locations=[os.path.dirname(original)])
                    external = importlib.util.module_from_spec(spec)
                    sys.modules['io_scene_valvesource'] = external
                    spec.loader.exec_module(external)
                external.register()
                try:
                    addon.register()
                    paths_config()
                    assert provider.status()[0] == 'EXTERNAL', provider.status()
                    assert provider.active_backend() is external
                    external.State.update_scene()
                    addon.unregister()
                    assert provider.backend_ready()
                    assert external.import_smd.SmdImporter.is_registered
                finally:
                    external.unregister()
                    # The supplied original also leaves 9 import-time vertex-map
                    # operators behind. Explicitly owned test cleanup only.
                    for map_name in external.vertex_maps:
                        for action in ('select', 'create', 'remove'):
                            name = 'vertex_map_' + action + '_' + map_name
                            if C.op_available('smd', name):
                                ident = getattr(bpy.ops.smd, name).get_rna_type().identifier
                                cls = bpy.types.Operator.bl_rna_get_subclass_py(ident)
                                if cls and cls.__module__.startswith('io_scene_valvesource.'):
                                    bpy.utils.unregister_class(cls)
                    # Original provider's known upstream unhook bug. Test-only
                    # cleanup; never modify the supplied original source.
                    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.load_post):
                        for callback in list(handlers):
                            if getattr(callback, '__module__', '').startswith('io_scene_valvesource'):
                                handlers.remove(callback)
                    addon.register()
                    paths_config()
                return 'External provider reused and left registered on parent disable'
            check('standalone_coexistence', coexistence)
        return rows
    finally:
        with open(os.path.join(out, 'source-results.json'), 'w', encoding='utf8') as stream:
            json.dump({'blender': bpy.app.version_string, 'module': addon.__name__,
                       'passed': sum(row['passed'] for row in rows),
                       'failed': sum(not row['passed'] for row in rows), 'tests': rows},
                      stream, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    root, out = sys.argv[sys.argv.index('--') + 1:]
    sys.path.insert(0, root)
    addon = importlib.import_module('bomberstudio_blender')
    addon.register()
    try:
        run(addon, out, standalone_root=root)
    finally:
        addon.unregister()
    assert not hasattr(bpy.types.Scene, 'vs')
    assert not any(getattr(h, '__module__', '').startswith('bomberstudio_blender.vendor')
                   for h in getattr(bpy.app.handlers, 'depsgraph_update_post', ()))
