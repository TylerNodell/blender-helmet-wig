import bpy


class HWG_PT_Input(bpy.types.Panel):
    bl_label = "Input"
    bl_idname = "HWG_PT_Input"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'HelmetWig'
    bl_order = 0

    def draw(self, context):
        props = context.scene.hwg
        layout = self.layout
        layout.use_property_split = True

        layout.prop(props, "scan_object")
        layout.prop(props, "meta_json_path")
        layout.operator("hwg.load_meta", icon='IMPORT')

        layout.separator()
        layout.prop(props, "scan_units")
        layout.prop(props, "scale_factor")


class HWG_PT_Base(bpy.types.Panel):
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

        layout.prop(props, "clearance_mm")
        layout.prop(props, "thickness_mm")
        layout.prop(props, "edge_ratio")
        layout.prop(props, "rim_height_mm")

        layout.separator()
        layout.operator("hwg.generate_base", icon='MOD_SOLIDIFY')


class HWG_PT_Vents(bpy.types.Panel):
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
