import bpy
from bpy.props import (
    FloatProperty,
    StringProperty,
    EnumProperty,
    BoolProperty,
    PointerProperty,
)


class HWG_SceneProps(bpy.types.PropertyGroup):
    """All helmet wig generator settings, stored per-scene."""

    # --- Measurements (user-facing: cm) ---
    head_circumference_cm: FloatProperty(
        name="Head Circumference",
        description="Tape around widest part: forehead, over ears, around occipital bump (cm)",
        default=57.0,
        min=1.0, soft_min=50.0, soft_max=65.0, max=100.0,
    )
    front_to_back_arc_cm: FloatProperty(
        name="Front-to-Back Arc",
        description="Forehead hairline, over crown, down to nape (cm)",
        default=36.0,
        min=1.0, soft_min=33.0, soft_max=40.0, max=60.0,
    )
    ear_to_ear_over_cm: FloatProperty(
        name="Ear-to-Ear Over Top",
        description="Top of left ear, over crown, to top of right ear (cm)",
        default=34.0,
        min=1.0, soft_min=30.0, soft_max=38.0, max=55.0,
    )
    ear_to_ear_back_cm: FloatProperty(
        name="Ear-to-Ear Around Back",
        description="Top of left ear, around back of head, to top of right ear (cm)",
        default=36.0,
        min=1.0, soft_min=30.0, soft_max=42.0, max=60.0,
    )
    head_width_cm: FloatProperty(
        name="Head Width",
        description="Side-to-side straight-line at widest point above ears (cm)",
        default=15.5,
        min=1.0, soft_min=13.0, soft_max=18.0, max=25.0,
    )
    head_depth_cm: FloatProperty(
        name="Head Depth",
        description="Forehead to back of skull straight-line at widest (cm)",
        default=19.5,
        min=1.0, soft_min=17.0, soft_max=23.0, max=30.0,
    )
    head_height_cm: FloatProperty(
        name="Head Height",
        description="Ear-top level to crown, straight-line (cm)",
        default=13.0,
        min=1.0, soft_min=10.0, soft_max=16.0, max=25.0,
    )
    forehead_width_cm: FloatProperty(
        name="Forehead Width",
        description="Temple to temple, straight across (cm)",
        default=12.5,
        min=1.0, soft_min=10.0, soft_max=15.0, max=20.0,
    )
    nape_width_cm: FloatProperty(
        name="Nape Width",
        description="Width at nape / base of skull (cm)",
        default=13.0,
        min=1.0, soft_min=10.0, soft_max=16.0, max=20.0,
    )
    forehead_height_cm: FloatProperty(
        name="Forehead Height",
        description="Hairline to brow ridge, measured flat (cm)",
        default=6.0,
        min=1.0, soft_min=4.0, soft_max=8.0, max=12.0,
    )

    # --- Crop ---
    edge_ratio: FloatProperty(
        name="Edge Ratio",
        description="Bottom cut height as fraction of head height (0.25 = cut bottom 25%)",
        default=0.25,
        min=0.05,
        max=0.60,
    )

    # --- Base ---
    clearance_mm: FloatProperty(
        name="Clearance (mm)",
        description="Outward offset from head surface for wig cap + comfort",
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
