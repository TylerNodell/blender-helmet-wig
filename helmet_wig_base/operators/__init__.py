from . import op_import_scan
from . import op_draw_hairline
from . import op_generate_base
from . import op_add_vents
from . import op_export_stl

classes = (
    op_import_scan.HWG_OT_ImportScan,
    op_draw_hairline.HWG_OT_DrawHairline,
    op_generate_base.HWG_OT_GenerateBase,
    op_add_vents.HWG_OT_AddVents,
    op_export_stl.HWG_OT_ExportSTL,
)


def register():
    import bpy
    for c in classes:
        bpy.utils.register_class(c)
    # Register persistent hairline overlay (green line always visible)
    op_draw_hairline.register_persistent_overlay()


def unregister():
    import bpy
    # Unregister persistent hairline overlay
    op_draw_hairline.unregister_persistent_overlay()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
