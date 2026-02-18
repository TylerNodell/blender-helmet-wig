from . import op_import_scan
from . import op_draw_hairline
from . import op_generate_base
from . import op_add_vents
from . import op_export_stl

import bpy

# In headless mode, the draw hairline operator (modal + GPU) can't be
# registered. Only register it when running with a GUI.
if bpy.app.background:
    classes = (
        op_import_scan.HWG_OT_ImportScan,
        op_generate_base.HWG_OT_GenerateBase,
        op_add_vents.HWG_OT_AddVents,
        op_export_stl.HWG_OT_ExportSTL,
    )
else:
    classes = (
        op_import_scan.HWG_OT_ImportScan,
        op_draw_hairline.HWG_OT_DrawHairline,
        op_generate_base.HWG_OT_GenerateBase,
        op_add_vents.HWG_OT_AddVents,
        op_export_stl.HWG_OT_ExportSTL,
    )


def register():
    for c in classes:
        bpy.utils.register_class(c)
    # Register persistent hairline overlay (green line always visible)
    # Only in GUI mode — no GPU context in headless.
    if not bpy.app.background:
        op_draw_hairline.register_persistent_overlay()


def unregister():
    if not bpy.app.background:
        op_draw_hairline.unregister_persistent_overlay()
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
