bl_info = {
    "name": "Helmet Wig Base Generator",
    "author": "Tyler Nodell",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > HelmetWig",
    "description": "Generate 3D-printable helmet wig bases from tape measurements.",
    "category": "Object",
}

from . import properties
from . import operators
from . import ui


def register():
    properties.register()
    operators.register()
    ui.register()


def unregister():
    ui.unregister()
    operators.unregister()
    properties.unregister()
