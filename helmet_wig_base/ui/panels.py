import bpy


class HWG_PT_Measurements(bpy.types.Panel):
    bl_label = "Measurements"
    bl_idname = "HWG_PT_Measurements"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'HelmetWig'
    bl_order = 0

    def draw(self, context):
        props = context.scene.hwg
        layout = self.layout
        layout.use_property_split = True

        layout.prop(props, "head_circumference_cm")

        box = layout.box()
        box.label(text="Arc Measurements", icon='CURVE_DATA')
        box.prop(props, "front_to_back_arc_cm")
        box.prop(props, "ear_to_ear_over_cm")
        box.prop(props, "ear_to_ear_back_cm")

        box = layout.box()
        box.label(text="Dimensions", icon='EMPTY_ARROWS')
        box.prop(props, "head_width_cm")
        box.prop(props, "head_depth_cm")
        box.prop(props, "head_height_cm")

        box = layout.box()
        box.label(text="Contour Details", icon='MOD_SMOOTH')
        box.prop(props, "forehead_width_cm")
        box.prop(props, "nape_width_cm")
        box.prop(props, "forehead_height_cm")


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
