import bpy
import os
import json
from datetime import datetime


class HWG_OT_ExportSTL(bpy.types.Operator):
    """Export the helmet base as STL + sidecar JSON."""
    bl_idname = "hwg.export_stl"
    bl_label = "Export STL"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.hwg
        obj = context.active_object

        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select the helmet base mesh to export.")
            return {'CANCELLED'}

        export_dir = bpy.path.abspath(props.export_dir)
        if not export_dir or not os.path.isdir(export_dir):
            try:
                os.makedirs(export_dir, exist_ok=True)
            except Exception as e:
                self.report({'ERROR'}, f"Cannot create export directory: {e}")
                return {'CANCELLED'}

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stl_name = f"helmet_base_{timestamp}.stl"
        stl_path = os.path.join(export_dir, stl_name)

        # Select only the target object
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # Export STL (Blender 4.x)
        try:
            bpy.ops.wm.stl_export(
                filepath=stl_path,
                export_selected_objects=True,
                global_scale=1.0,
                ascii_format=False,
            )
        except AttributeError:
            # Fallback for older Blender builds
            bpy.ops.export_mesh.stl(
                filepath=stl_path,
                use_selection=True,
                global_scale=1.0,
                ascii=False,
            )

        # Write sidecar JSON
        json_path = os.path.join(export_dir, f"helmet_base_{timestamp}.json")
        bbox = [obj.matrix_world @ bpy.mathutils.Vector(c) for c in obj.bound_box]

        # Safer: import mathutils at module level or inline
        from mathutils import Vector
        bbox = [obj.matrix_world @ Vector(c) for c in obj.bound_box]

        sidecar = {
            "version": "1.0.0",
            "exportTimestamp": datetime.now().isoformat(),
            "units": "mm",
            "sourceObject": obj.name,
            "parameters": {
                "clearanceMm": props.clearance_mm,
                "thicknessMm": props.thickness_mm,
                "edgeRatio": props.edge_ratio,
                "rimHeightMm": props.rim_height_mm,
                "ventsEnabled": props.vents_enabled,
                "ventPattern": props.vent_pattern,
                "ventRadiusMm": props.vent_radius_mm,
                "ventSpacingMm": props.vent_spacing_mm,
            },
            "boundingBox": {
                "minMm": [min(v.x for v in bbox), min(v.y for v in bbox), min(v.z for v in bbox)],
                "maxMm": [max(v.x for v in bbox), max(v.y for v in bbox), max(v.z for v in bbox)],
            },
            "stlFile": stl_name,
        }

        with open(json_path, 'w') as f:
            json.dump(sidecar, f, indent=2)

        self.report({'INFO'}, f"Exported: {stl_path}")
        return {'FINISHED'}
