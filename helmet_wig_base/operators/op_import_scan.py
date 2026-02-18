"""Import a head scan mesh (OBJ/STL/PLY/FBX) and prepare it for helmet generation.

Handles:
- File import via Blender's built-in importers
- Auto-scaling from scan units (meters → mm for ARKit/LiDAR scans)
- Centering on geometry bounds
- Auto-assignment as the active scan object in properties
"""

import bpy
import os


class HWG_OT_ImportScan(bpy.types.Operator):
    """Import a 3D head scan file and set it as the active scan object."""

    bl_idname = "hwg.import_scan"
    bl_label = "Import Head Scan"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the head scan file",
        subtype='FILE_PATH',
    )

    filter_glob: bpy.props.StringProperty(
        default="*.obj;*.stl;*.ply;*.fbx;*.glb;*.gltf",
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        """Open a file browser dialog."""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        props = context.scene.hwg

        if not self.filepath:
            self.report({'ERROR'}, "No file selected.")
            return {'CANCELLED'}

        filepath = bpy.path.abspath(self.filepath)
        if not os.path.isfile(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}

        ext = os.path.splitext(filepath)[1].lower()

        # Track objects before import to find the new ones
        existing_objects = set(bpy.data.objects[:])

        # Import based on file extension
        try:
            if ext == '.obj':
                bpy.ops.wm.obj_import(filepath=filepath)
            elif ext == '.stl':
                try:
                    bpy.ops.wm.stl_import(filepath=filepath)
                except AttributeError:
                    bpy.ops.import_mesh.stl(filepath=filepath)
            elif ext == '.ply':
                try:
                    bpy.ops.wm.ply_import(filepath=filepath)
                except AttributeError:
                    bpy.ops.import_mesh.ply(filepath=filepath)
            elif ext == '.fbx':
                bpy.ops.import_scene.fbx(filepath=filepath)
            elif ext in ('.glb', '.gltf'):
                bpy.ops.import_scene.gltf(filepath=filepath)
            else:
                self.report({'ERROR'}, f"Unsupported file format: {ext}")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {e}")
            return {'CANCELLED'}

        # Find newly imported objects
        new_objects = [obj for obj in bpy.data.objects if obj not in existing_objects]
        if not new_objects:
            self.report({'ERROR'}, "No objects were imported.")
            return {'CANCELLED'}

        # Find the mesh object (prefer largest by vertex count)
        mesh_objects = [obj for obj in new_objects if obj.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, "No mesh objects found in imported file.")
            return {'CANCELLED'}

        scan_obj = max(mesh_objects, key=lambda o: len(o.data.vertices))

        # Clean up any non-mesh imported objects (cameras, lights, empties)
        for obj in new_objects:
            if obj != scan_obj and obj.type != 'MESH':
                bpy.data.objects.remove(obj, do_unlink=True)

        # Name it clearly
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        scan_obj.name = f"{base_name}_SCAN"

        # Apply scale from scan units to convert to mm (working units)
        if props.scan_units == 'M':
            unit_scale = 1000.0  # meters → mm
        elif props.scan_units == 'CM':
            unit_scale = 10.0    # centimeters → mm
        else:
            unit_scale = 1.0     # already mm
        total_scale = unit_scale * props.scale_factor

        if abs(total_scale - 1.0) > 0.0001:
            scan_obj.scale = (total_scale, total_scale, total_scale)
            bpy.ops.object.select_all(action='DESELECT')
            scan_obj.select_set(True)
            context.view_layer.objects.active = scan_obj
            with bpy.context.temp_override(
                object=scan_obj,
                active_object=scan_obj,
                selected_objects=[scan_obj],
            ):
                bpy.ops.object.transform_apply(
                    location=False, rotation=False, scale=True
                )

        # Center on geometry bounds
        bpy.ops.object.select_all(action='DESELECT')
        scan_obj.select_set(True)
        context.view_layer.objects.active = scan_obj
        with bpy.context.temp_override(
            object=scan_obj,
            active_object=scan_obj,
            selected_objects=[scan_obj],
        ):
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        scan_obj.location = (0.0, 0.0, 0.0)

        # Auto-assign as the scan object
        props.scan_object = scan_obj

        vert_count = len(scan_obj.data.vertices)
        tri_count = len(scan_obj.data.polygons)
        self.report(
            {'INFO'},
            f"Imported: {scan_obj.name} ({vert_count:,} verts, {tri_count:,} faces, "
            f"scale={total_scale:.1f}x)",
        )
        return {'FINISHED'}
