import bpy
import json
import os


class HWG_OT_LoadMeta(bpy.types.Operator):
    """Load meta.json from the iOS head scan export and apply scale settings."""
    bl_idname = "hwg.load_meta"
    bl_label = "Load meta.json"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hwg
        path = bpy.path.abspath(props.meta_json_path)

        if not path or not os.path.isfile(path):
            self.report({'ERROR'}, f"meta.json not found: {path}")
            return {'CANCELLED'}

        try:
            with open(path, 'r') as f:
                meta = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to parse meta.json: {e}")
            return {'CANCELLED'}

        # Determine scan units
        units = meta.get("units", "meters").lower()
        if units in ("meters", "m"):
            props.scan_units = 'M'
        elif units in ("millimeters", "mm"):
            props.scan_units = 'MM'
        else:
            self.report({'WARNING'}, f"Unknown units '{units}', assuming meters.")
            props.scan_units = 'M'

        # Extract circumference scale factor if present
        circ = meta.get("circumferenceMeasurement")
        if circ and circ.get("scaleFactor"):
            props.scale_factor = circ["scaleFactor"]
            self.report({'INFO'}, f"Scale factor from circumference: {props.scale_factor:.4f}")
        else:
            props.scale_factor = 1.0

        # Log mesh stats
        vc = meta.get("vertexCount", "?")
        tc = meta.get("triangleCount", "?")
        self.report({'INFO'}, f"Loaded meta.json: {vc} verts, {tc} tris, units={units}")

        return {'FINISHED'}
