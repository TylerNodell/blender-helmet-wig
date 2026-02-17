from . import panels

classes = (
    panels.HWG_PT_Measurements,
    panels.HWG_PT_Base,
    panels.HWG_PT_Vents,
    panels.HWG_PT_Export,
)


def register():
    import bpy
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    import bpy
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
