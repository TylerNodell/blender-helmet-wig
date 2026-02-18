import bpy


class HWG_PT_Input(bpy.types.Panel):
    """Import & select a head scan mesh."""

    bl_label = "Head Scan"
    bl_idname = "HWG_PT_Input"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'HelmetWig'
    bl_order = 0

    def draw(self, context):
        props = context.scene.hwg
        layout = self.layout
        layout.use_property_split = True

        # Import button
        layout.operator("hwg.import_scan", icon='IMPORT', text="Import Scan File")

        layout.separator()

        # Scan object picker (auto-set on import, or manual pick)
        layout.prop(props, "scan_object")

        # Show scan info if an object is selected
        if props.scan_object and props.scan_object.type == 'MESH':
            box = layout.box()
            mesh = props.scan_object.data
            box.label(text=f"Vertices: {len(mesh.vertices):,}", icon='VERTEXSEL')
            box.label(text=f"Faces: {len(mesh.polygons):,}", icon='FACESEL')

        layout.separator()

        # Scale settings
        layout.prop(props, "scan_units")
        layout.prop(props, "scale_factor")


class HWG_PT_Base(bpy.types.Panel):
    """Configure and generate the helmet shell."""

    bl_label = "Base Generation"
    bl_idname = "HWG_PT_Base"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'HelmetWig'
    bl_order = 1

    def draw(self, context):
        props = context.scene.hwg
        layout = self.layout
        layout.use_property_split = True

        layout.prop(props, "shell_mode")

        layout.separator()

        if props.shell_mode == 'WIG_CAP':
            # Draw hairline button + status
            row = layout.row(align=True)
            row.scale_y = 1.3
            row.operator("hwg.draw_hairline", icon='GREASEPENCIL')

            if props.hairline_points_json:
                import json
                try:
                    pts = json.loads(props.hairline_points_json)
                    layout.label(
                        text=f"Hairline: {len(pts)} points",
                        icon='CHECKMARK',
                    )
                except (json.JSONDecodeError, TypeError):
                    layout.label(text="Hairline: invalid data", icon='ERROR')
            else:
                layout.label(text="No hairline drawn", icon='INFO')

            layout.separator()
        else:
            # HELMET mode: flat edge ratio
            layout.prop(props, "edge_ratio")

        layout.prop(props, "clearance_mm")
        layout.prop(props, "thickness_mm")
        layout.prop(props, "rim_height_mm")

        layout.separator()
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("hwg.generate_base", icon='MOD_SOLIDIFY')


class HWG_PT_Vents(bpy.types.Panel):
    """Add ventilation holes to the helmet."""

    bl_label = "Vents"
    bl_idname = "HWG_PT_Vents"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'HelmetWig'
    bl_order = 2

    def draw(self, context):
        props = context.scene.hwg
        layout = self.layout
        layout.use_property_split = True

        layout.prop(props, "vents_enabled")

        col = layout.column()
        col.enabled = props.vents_enabled
        col.prop(props, "vent_pattern")
        col.prop(props, "vent_radius_mm")
        col.prop(props, "vent_spacing_mm")
        col.prop(props, "vent_margin_mm")

        layout.separator()
        row = layout.row()
        row.enabled = props.vents_enabled
        row.operator("hwg.add_vents", icon='MESH_CIRCLE')


class HWG_PT_Export(bpy.types.Panel):
    """Export the finished helmet as STL."""

    bl_label = "Export"
    bl_idname = "HWG_PT_Export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'HelmetWig'
    bl_order = 3

    def draw(self, context):
        props = context.scene.hwg
        layout = self.layout
        layout.use_property_split = True

        layout.prop(props, "export_dir")
        layout.operator("hwg.export_stl", icon='EXPORT')


classes = (
    HWG_PT_Input,
    HWG_PT_Base,
    HWG_PT_Vents,
    HWG_PT_Export,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
