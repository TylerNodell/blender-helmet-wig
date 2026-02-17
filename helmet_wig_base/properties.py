import bpy
from bpy.props import (
    FloatProperty,
    IntProperty,
    StringProperty,
    EnumProperty,
    BoolProperty,
    PointerProperty,
)


class HWG_SceneProps(bpy.types.PropertyGroup):
    """All helmet wig generator settings, stored per-scene."""

    # --- Input ---
    scan_object: PointerProperty(
        name="Scan Object",
        description="The imported head scan mesh",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'MESH',
    )
    meta_json_path: StringProperty(
        name="meta.json",
        description="Path to the scan metadata JSON file",
        subtype='FILE_PATH',
        default="",
    )

    # --- Scale ---
    scan_units: EnumProperty(
        name="Scan Units",
        items=[
            ('M', "Meters", "Scan is in meters (ARKit default)"),
            ('MM', "Millimeters", "Scan is already in mm"),
        ],
        default='M',
    )
    scale_factor: FloatProperty(
        name="Scale Factor",
        description="Computed or manual scale correction factor",
        default=1.0,
        min=0.01,
        max=100.0,
    )

    # --- Crop ---
    edge_ratio: FloatProperty(
        name="Edge Ratio",
        description="Bottom cut height as fraction of scan height (0.25 = cut bottom 25%)",
        default=0.25,
        min=0.05,
        max=0.60,
    )

    # --- Base ---
    clearance_mm: FloatProperty(
        name="Clearance (mm)",
        description="Outward offset from scan surface for wig cap + comfort",
        default=4.0,
        min=0.0,
        max=20.0,
    )
    thickness_mm: FloatProperty(
        name="Shell Thickness (mm)",
        description="Wall thickness of the PETG shell",
        default=2.8,
        min=0.5,
        max=10.0,
    )
    rim_height_mm: FloatProperty(
        name="Rim Height (mm)",
        description="Height of the stiffening rim band at the bottom edge",
        default=8.0,
        min=0.0,
        max=30.0,
    )

    # --- Vents ---
    vents_enabled: BoolProperty(
        name="Add Vents",
        default=True,
    )
    vent_pattern: EnumProperty(
        name="Vent Pattern",
        items=[
            ('CIRCLES', "Circles", "Round vent holes"),
            ('HEX', "Hexagons", "Hexagonal pattern"),
            ('SLOTS', "Slots", "Elongated slot vents"),
        ],
        default='CIRCLES',
    )
    vent_radius_mm: FloatProperty(
        name="Vent Radius (mm)",
        description="Radius of each vent hole",
        default=6.0,
        min=1.0,
        max=30.0,
    )
    vent_spacing_mm: FloatProperty(
        name="Vent Spacing (mm)",
        description="Center-to-center distance between vents",
        default=18.0,
        min=5.0,
        max=60.0,
    )
    vent_margin_mm: FloatProperty(
        name="Vent Margin (mm)",
        description="Keep-out zone from rim edge (no vents within this distance)",
        default=15.0,
        min=0.0,
        max=50.0,
    )

    # --- Export ---
    export_dir: StringProperty(
        name="Export Directory",
        subtype='DIR_PATH',
        default="//",
    )


classes = (HWG_SceneProps,)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.hwg = PointerProperty(type=HWG_SceneProps)


def unregister():
    del bpy.types.Scene.hwg
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
