"""Headless test harness for the Helmet Wig Base add-on.

Runs the full wig cap generation pipeline in Blender --background mode:
  1. Clear scene, import head model
  2. Load hairline config (JSON points)
  3. Enable add-on, run generation
  4. Validate output mesh (metrics)
  5. Set up camera + lighting
  6. Render multi-angle screenshots
  7. Export output mesh + metrics

Usage:
  blender --background --python test_harness.py -- \
    --head-model tests/fixtures/BaldGuy-LP_head.obj \
    --hairline-config tests/fixtures/hairline_default.json \
    --output-dir output \
    --render-dir renders
"""

import bpy
import bmesh
import json
import math
import os
import sys
import time
from mathutils import Vector


def parse_args():
    """Parse CLI args after '--' separator."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    import argparse
    parser = argparse.ArgumentParser(description="Headless wig base test harness")
    parser.add_argument("--head-model", required=True, help="Path to head OBJ/STL")
    parser.add_argument("--hairline-config", required=True,
                        help="Path to hairline JSON [[x,y,z], ...]")
    parser.add_argument("--output-dir", default="output",
                        help="Directory for mesh export + metrics")
    parser.add_argument("--render-dir", default="renders",
                        help="Directory for rendered PNGs")
    parser.add_argument("--shell-mode", default="WIG_CAP",
                        choices=["WIG_CAP"],
                        help="Shell generation mode (WIG_CAP only)")
    parser.add_argument("--clearance", type=float, default=None,
                        help="Clearance in mm (overrides default)")
    parser.add_argument("--thickness", type=float, default=None,
                        help="Shell thickness in mm (overrides default)")
    parser.add_argument("--scan-units", default="cm",
                        choices=["mm", "cm", "m"],
                        help="Unit system of the head model file (default: cm)")
    parser.add_argument("--resolution", default="1024x1024",
                        help="Render resolution WxH")
    parser.add_argument("--skip-render", action="store_true",
                        help="Skip rendering (just generate + export)")
    parser.add_argument("--test-label", default="",
                        help="Label for the tiled overview image (e.g. 'Test 1')")
    parser.add_argument("--tile-output", default="",
                        help="Path for tiled overview image (default: <render-dir>/tiled.png)")
    return parser.parse_args(argv)


# ------------------------------------------------------------------
# Pipeline steps
# ------------------------------------------------------------------

def clear_scene():
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    # Clean orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)


def import_head(filepath):
    """Import a head mesh. Returns the imported object."""
    filepath = os.path.abspath(filepath)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Head model not found: {filepath}")

    bpy.ops.object.select_all(action='DESELECT')

    ext = filepath.lower().rsplit(".", 1)[-1]
    if ext == "obj":
        bpy.ops.wm.obj_import(filepath=filepath)
    elif ext == "stl":
        bpy.ops.wm.stl_import(filepath=filepath)
    elif ext == "fbx":
        bpy.ops.import_scene.fbx(filepath=filepath)
    elif ext in ("glb", "gltf"):
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif ext == "ply":
        bpy.ops.wm.ply_import(filepath=filepath)
    else:
        raise ValueError(f"Unsupported format: {ext}")

    if not bpy.context.selected_objects:
        raise RuntimeError("Import produced no objects")

    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj
    print(f"  Imported: {obj.name} ({len(obj.data.vertices):,} verts, "
          f"{len(obj.data.polygons):,} faces)")
    return obj


def get_unit_scale(scan_units):
    """Return the multiplier to convert scan_units to millimeters."""
    if scan_units == "m":
        return 1000.0
    elif scan_units == "cm":
        return 10.0
    else:  # mm
        return 1.0


def apply_unit_scale(obj, scale_factor):
    """Scale an object and apply the transform so vertices are in mm."""
    if abs(scale_factor - 1.0) < 0.0001:
        return
    obj.scale = (scale_factor, scale_factor, scale_factor)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(
        object=obj, active_object=obj, selected_objects=[obj]
    ):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    print(f"  Scaled {obj.name} by {scale_factor}x "
          f"({len(obj.data.vertices):,} verts now in mm)")


def center_on_geometry(obj):
    """Center an object on its geometry bounds, matching op_import_scan.py behavior.

    This replicates what the Import Scan operator does:
    1. Set origin to geometry bounding box center
    2. Move object to world origin (0, 0, 0)

    The hairline points are drawn on the centered head, so the test harness
    must center the head the same way for coordinates to match.
    """
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(
        object=obj, active_object=obj, selected_objects=[obj]
    ):
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    obj.location = (0.0, 0.0, 0.0)

    # Log the new bounding box for debugging
    mat = obj.matrix_world
    bbox = [mat @ Vector(c) for c in obj.bound_box]
    xs = [v.x for v in bbox]
    ys = [v.y for v in bbox]
    zs = [v.z for v in bbox]
    print(f"  Centered {obj.name} at origin")
    print(f"    BBox: X=[{min(xs):.1f}, {max(xs):.1f}] "
          f"Y=[{min(ys):.1f}, {max(ys):.1f}] "
          f"Z=[{min(zs):.1f}, {max(zs):.1f}]")


def scale_hairline_json(hairline_json_str, scale_factor):
    """Scale hairline point coordinates by the given factor.

    The hairline was drawn on the unscaled model (in original units),
    so it needs the same scaling to match the mm-scaled mesh.
    """
    if abs(scale_factor - 1.0) < 0.0001:
        return hairline_json_str
    pts = json.loads(hairline_json_str)
    scaled = [[p[0] * scale_factor, p[1] * scale_factor, p[2] * scale_factor]
              for p in pts]
    return json.dumps(scaled)


def enable_addon():
    """Enable the helmet_wig_base add-on."""
    # Add the repo root to Blender's addon paths
    repo_root = os.path.dirname(os.path.abspath(__file__))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # Also add to Blender's script directories for addon discovery
    scripts_dir = os.path.join(
        bpy.utils.resource_path('USER'),
        "scripts", "addons"
    )

    try:
        bpy.ops.preferences.addon_enable(module="helmet_wig_base")
        print("  Add-on enabled via preferences")
    except Exception:
        # Manual registration fallback
        import helmet_wig_base
        helmet_wig_base.register()
        print("  Add-on registered manually")


def configure_props(args, hairline_json_str):
    """Set up scene properties for generation."""
    props = bpy.context.scene.hwg

    # Find the head object (should be the only mesh in scene)
    head_obj = None
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            head_obj = obj
            break

    if not head_obj:
        raise RuntimeError("No mesh object found in scene")

    props.scan_object = head_obj
    props.shell_mode = args.shell_mode

    if args.clearance is not None:
        props.clearance_mm = args.clearance
    if args.thickness is not None:
        props.thickness_mm = args.thickness

    # Set hairline data
    if args.shell_mode == 'WIG_CAP':
        props.hairline_points_json = hairline_json_str
        pts = json.loads(hairline_json_str)
        print(f"  Hairline: {len(pts)} points loaded")

    print(f"  Mode: {props.shell_mode}")
    print(f"  Clearance: {props.clearance_mm}mm")
    print(f"  Thickness: {props.thickness_mm}mm")
    print(f"  Scan object: {head_obj.name}")


def run_generation():
    """Run the wig base generation operator."""
    result = bpy.ops.hwg.generate_base()
    if 'CANCELLED' in result:
        raise RuntimeError("Generation operator returned CANCELLED")
    print(f"  Generation result: {result}")

    # Find the generated shell
    shell = bpy.context.active_object
    if shell:
        print(f"  Generated: {shell.name} ({len(shell.data.vertices):,} verts, "
              f"{len(shell.data.polygons):,} faces)")
    return shell


def compute_metrics(shell_obj, head_obj):
    """Compute mesh quality metrics."""
    mesh = shell_obj.data
    mat = shell_obj.matrix_world
    bbox = [mat @ Vector(c) for c in shell_obj.bound_box]

    metrics = {
        "vertex_count": len(mesh.vertices),
        "edge_count": len(mesh.edges),
        "face_count": len(mesh.polygons),
        "bbox": {
            "min": [min(v.x for v in bbox), min(v.y for v in bbox), min(v.z for v in bbox)],
            "max": [max(v.x for v in bbox), max(v.y for v in bbox), max(v.z for v in bbox)],
        },
        "dimensions": {
            "width": max(v.x for v in bbox) - min(v.x for v in bbox),
            "depth": max(v.y for v in bbox) - min(v.y for v in bbox),
            "height": max(v.z for v in bbox) - min(v.z for v in bbox),
        },
    }

    # Check manifold (watertight)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    non_manifold_edges = [e for e in bm.edges if not e.is_manifold]
    boundary_edges = [e for e in bm.edges if e.is_boundary]
    metrics["is_manifold"] = len(non_manifold_edges) == 0
    metrics["non_manifold_edges"] = len(non_manifold_edges)
    metrics["boundary_edges"] = len(boundary_edges)

    # Check loose geometry
    loose_verts = [v for v in bm.verts if not v.link_faces]
    metrics["loose_vertices"] = len(loose_verts)

    # Connected components
    if bm.verts:
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        visited = set()
        components = 0
        for v in bm.verts:
            if v.index not in visited:
                components += 1
                queue = [v.index]
                visited.add(v.index)
                while queue:
                    vi = queue.pop()
                    for e in bm.verts[vi].link_edges:
                        oi = e.other_vert(bm.verts[vi]).index
                        if oi not in visited:
                            visited.add(oi)
                            queue.append(oi)
        metrics["connected_components"] = components

    bm.free()
    return metrics


def setup_camera_and_lights(shell_obj):
    """Create a camera rig and 3-point lighting for multi-angle renders."""
    mat = shell_obj.matrix_world
    bbox = [mat @ Vector(c) for c in shell_obj.bound_box]
    center = sum(bbox, Vector()) / 8.0
    max_dim = max(
        max(v.x for v in bbox) - min(v.x for v in bbox),
        max(v.y for v in bbox) - min(v.y for v in bbox),
        max(v.z for v in bbox) - min(v.z for v in bbox),
    )

    # Camera distance based on object size
    cam_dist = max_dim * 1.8

    # Create camera
    cam_data = bpy.data.cameras.new("HWG_TestCam")
    cam_data.lens = 50
    cam_obj = bpy.data.objects.new("HWG_TestCam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    # Bright ambient world lighting for clear visibility
    world = bpy.data.worlds.new("HWG_World")
    world.use_nodes = True
    bg_node = world.node_tree.nodes.get("Background")
    if bg_node:
        bg_node.inputs["Strength"].default_value = 0.8
        bg_node.inputs["Color"].default_value = (0.7, 0.72, 0.75, 1.0)
    bpy.context.scene.world = world

    # 4-point lighting — very bright for clear visibility at any scale
    # Energy scaled with distance^2 for consistent brightness
    energy_scale = (max_dim / 200.0) ** 2
    for name, loc, base_energy in [
        ("Key",  (cam_dist * 0.8, -cam_dist * 0.6, cam_dist * 0.8), 500000),
        ("Fill", (-cam_dist * 0.6, -cam_dist * 0.4, cam_dist * 0.5), 300000),
        ("Rim",  (-cam_dist * 0.2, cam_dist * 0.8, cam_dist * 0.6), 350000),
        ("Under", (0, -cam_dist * 0.3, -cam_dist * 0.4), 200000),
    ]:
        light_data = bpy.data.lights.new(f"HWG_{name}", 'AREA')
        light_data.energy = base_energy * energy_scale
        light_data.size = max_dim * 0.8
        light_obj = bpy.data.objects.new(f"HWG_{name}", light_data)
        light_obj.location = Vector(loc) + center
        bpy.context.collection.objects.link(light_obj)

    # Shell material — bright cyan-blue for high visibility
    shell_mat = bpy.data.materials.new("HWG_Shell_Mat")
    shell_mat.use_nodes = True
    nodes = shell_mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.5, 0.75, 1.0, 1.0)
        bsdf.inputs["Alpha"].default_value = 0.85
        bsdf.inputs["Roughness"].default_value = 0.35
        # Add some metallic sheen for better edge definition
        bsdf.inputs["Metallic"].default_value = 0.1
    if hasattr(shell_mat, 'blend_method'):
        shell_mat.blend_method = 'BLEND'
    shell_obj.data.materials.clear()
    shell_obj.data.materials.append(shell_mat)

    # Head material — skin tone
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj != shell_obj:
            head_mat = bpy.data.materials.new("HWG_Head_Mat")
            head_mat.use_nodes = True
            h_nodes = head_mat.node_tree.nodes
            h_bsdf = h_nodes.get("Principled BSDF")
            if h_bsdf:
                h_bsdf.inputs["Base Color"].default_value = (0.85, 0.75, 0.65, 1.0)
                h_bsdf.inputs["Roughness"].default_value = 0.6
            obj.data.materials.clear()
            obj.data.materials.append(head_mat)

    return cam_obj, center, cam_dist


def render_angles(cam_obj, center, cam_dist, render_dir, resolution, head_obj=None):
    """Render the scene from multiple angles.

    For each angle, renders TWO images:
      - <angle>_with_head.png  — shell + head visible (verify fit/clearance)
      - <angle>_shell_only.png — head hidden (inspect shell for holes/flaps)
    """
    w, h = [int(x) for x in resolution.split("x")]
    scene = bpy.context.scene
    # EEVEE was renamed to EEVEE_NEXT in Blender 4.2
    if bpy.app.version >= (4, 2, 0):
        scene.render.engine = 'BLENDER_EEVEE_NEXT'
    else:
        scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'

    # Camera angles: (name, azimuth_deg, elevation_deg)
    # Row 1: Standard views (eye-level + top)
    # Row 2: Angled-from-below views looking up to check underside/rim
    angles = [
        ("front", 0, 15),
        ("left", 90, 15),
        ("right", -90, 15),
        ("back", 180, 15),
        ("top", 0, 80),
        ("below_front", 0, -35),       # Looking up from below, front
        ("below_left", 90, -35),       # Looking up from below, left
        ("below_right", -90, -35),     # Looking up from below, right
        ("below_back", 180, -35),      # Looking up from below, back
        ("quarter_front_left", 45, 20),
    ]

    for name, azimuth, elevation in angles:
        az_rad = math.radians(azimuth)
        el_rad = math.radians(elevation)

        # Spherical to cartesian
        x = cam_dist * math.cos(el_rad) * math.sin(az_rad)
        y = cam_dist * math.cos(el_rad) * -math.cos(az_rad)
        z = cam_dist * math.sin(el_rad)

        cam_obj.location = center + Vector((x, y, z))

        # Point camera at center
        direction = center - cam_obj.location
        rot_quat = direction.to_track_quat('-Z', 'Y')
        cam_obj.rotation_euler = rot_quat.to_euler()

        # --- Pass 1: Render WITH head visible ---
        if head_obj:
            head_obj.hide_render = False
            head_obj.hide_viewport = False
        filepath_with = os.path.join(
            os.path.abspath(render_dir), f"{name}_with_head.png"
        )
        scene.render.filepath = filepath_with
        bpy.ops.render.render(write_still=True)
        print(f"  Rendered: {name}_with_head.png")

        # --- Pass 2: Render WITHOUT head (shell only) ---
        if head_obj:
            head_obj.hide_render = True
            head_obj.hide_viewport = True
        filepath_shell = os.path.join(
            os.path.abspath(render_dir), f"{name}_shell_only.png"
        )
        scene.render.filepath = filepath_shell
        bpy.ops.render.render(write_still=True)
        print(f"  Rendered: {name}_shell_only.png")

        # Restore head visibility for next angle
        if head_obj:
            head_obj.hide_render = False
            head_obj.hide_viewport = False


def create_tiled_image(render_dir, output_path, test_label="Test"):
    """Composite all rendered images into a single tiled overview image.

    Creates a grid layout:
      Row 1: All with_head angles
      Row 2: All shell_only angles
    Each tile is labeled with the angle name.

    Args:
        render_dir: Directory containing rendered PNGs.
        output_path: Path for the output tiled image.
        test_label: Label text drawn at the top of the image.
    """
    # Collect rendered images, sorted into with_head and shell_only
    angles = ["front", "left", "right", "back", "top",
              "below_front", "below_left", "below_right", "below_back",
              "quarter_front_left"]

    with_head_files = []
    shell_only_files = []
    for angle in angles:
        wh = os.path.join(os.path.abspath(render_dir), f"{angle}_with_head.png")
        so = os.path.join(os.path.abspath(render_dir), f"{angle}_shell_only.png")
        if os.path.exists(wh):
            with_head_files.append((angle, wh))
        if os.path.exists(so):
            shell_only_files.append((angle, so))

    if not with_head_files and not shell_only_files:
        print("  No render images found for tiling.")
        return

    # Load the first image to get tile dimensions
    first_path = (with_head_files or shell_only_files)[0][1]
    ref_img = bpy.data.images.load(first_path, check_existing=False)
    tile_w = ref_img.size[0]
    tile_h = ref_img.size[1]
    bpy.data.images.remove(ref_img)

    # Grid: 2 rows (with_head, shell_only) × N columns (angles)
    cols = max(len(with_head_files), len(shell_only_files))
    if cols == 0:
        print("  No images to tile.")
        return

    # Add space for labels: 40px top banner + 30px per-row label
    label_height = 40
    row_label_height = 30
    total_w = cols * tile_w
    total_h = label_height + 2 * (row_label_height + tile_h)

    # Create output image
    tile_img = bpy.data.images.new(
        "HWG_Tiled", width=total_w, height=total_h,
        alpha=True, float_buffer=False,
    )

    # Initialize all pixels to dark gray background (RGBA)
    num_pixels = total_w * total_h
    bg_color = [0.15, 0.15, 0.15, 1.0]
    pixels = bg_color * num_pixels
    tile_img.pixels[:] = pixels

    def blit_image(src_path, dest_x, dest_y):
        """Copy src image pixels into tile_img at (dest_x, dest_y) from bottom-left."""
        src_img = bpy.data.images.load(src_path, check_existing=False)
        src_w, src_h = src_img.size[0], src_img.size[1]
        src_pixels = list(src_img.pixels[:])
        dest_pixels = list(tile_img.pixels[:])

        for row in range(src_h):
            if dest_y + row >= total_h:
                break
            src_start = row * src_w * 4
            src_end = src_start + src_w * 4
            dest_row = dest_y + row
            dest_start = (dest_row * total_w + dest_x) * 4
            dest_end = dest_start + src_w * 4
            if dest_end <= len(dest_pixels) and src_end <= len(src_pixels):
                dest_pixels[dest_start:dest_end] = src_pixels[src_start:src_end]

        tile_img.pixels[:] = dest_pixels
        bpy.data.images.remove(src_img)

    def draw_text_bar(y_start, height, text, color=(1.0, 1.0, 1.0, 1.0)):
        """Draw a solid color bar with simple text indicator.

        Since Blender's image API doesn't support text rendering directly,
        we draw a colored bar as a visual separator. The text label is
        encoded in the filename instead.
        """
        dest_pixels = list(tile_img.pixels[:])
        bar_color = [0.08, 0.08, 0.08, 1.0]  # near-black bar

        for row in range(height):
            for col in range(total_w):
                idx = ((y_start + row) * total_w + col) * 4
                if idx + 3 < len(dest_pixels):
                    dest_pixels[idx:idx + 4] = bar_color

        # Draw a small colored indicator line at the left edge
        indicator_color = list(color)
        for row in range(2, height - 2):
            for col in range(4, min(200, total_w)):
                idx = ((y_start + row) * total_w + col) * 4
                if idx + 3 < len(dest_pixels):
                    dest_pixels[idx:idx + 4] = indicator_color

        tile_img.pixels[:] = dest_pixels

    # Blender images have origin at bottom-left, so we build from bottom up
    # Layout (from bottom to top):
    #   Row 2 tiles (shell_only) at y=0
    #   Row 2 label bar
    #   Row 1 tiles (with_head)
    #   Row 1 label bar
    #   Top banner

    y_cursor = 0

    # Row 2: Shell only
    for col_idx, (angle, fpath) in enumerate(shell_only_files):
        blit_image(fpath, col_idx * tile_w, y_cursor)
    y_cursor += tile_h

    # Row 2 label bar
    draw_text_bar(y_cursor, row_label_height, "SHELL ONLY",
                  color=(0.4, 0.6, 0.9, 1.0))
    y_cursor += row_label_height

    # Row 1: With head
    for col_idx, (angle, fpath) in enumerate(with_head_files):
        blit_image(fpath, col_idx * tile_w, y_cursor)
    y_cursor += tile_h

    # Row 1 label bar
    draw_text_bar(y_cursor, row_label_height, "WITH HEAD",
                  color=(0.85, 0.75, 0.65, 1.0))
    y_cursor += row_label_height

    # Top banner
    draw_text_bar(y_cursor, label_height, test_label,
                  color=(0.2, 0.8, 0.2, 1.0))

    # Save
    tile_img.filepath_raw = os.path.abspath(output_path)
    tile_img.file_format = 'PNG'
    tile_img.save()
    bpy.data.images.remove(tile_img)
    print(f"  Tiled image saved: {output_path}")


def export_mesh(shell_obj, output_dir):
    """Export the shell as STL."""
    bpy.ops.object.select_all(action='DESELECT')
    shell_obj.select_set(True)
    bpy.context.view_layer.objects.active = shell_obj

    stl_path = os.path.join(os.path.abspath(output_dir), "wig_base.stl")
    try:
        bpy.ops.wm.stl_export(
            filepath=stl_path,
            export_selected_objects=True,
        )
    except AttributeError:
        bpy.ops.export_mesh.stl(filepath=stl_path, use_selection=True)

    print(f"  Exported: {stl_path}")
    return stl_path


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    start_time = time.time()
    args = parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.render_dir, exist_ok=True)

    print("=" * 60)
    print("HWG Test Harness")
    print("=" * 60)

    # Compute unit scale once (used for head + hairline)
    unit_scale = get_unit_scale(args.scan_units)
    print(f"\n  Scan units: {args.scan_units} (scale {unit_scale}x to mm)")

    # Step 1: Clear and import
    print("\n--- Step 1: Import head model ---")
    clear_scene()
    head = import_head(args.head_model)

    # Step 1b: Scale head model to millimeters
    if unit_scale != 1.0:
        print(f"\n--- Step 1b: Scale head {args.scan_units} -> mm ---")
        apply_unit_scale(head, unit_scale)

    # Step 1c: Center on geometry bounds — matches op_import_scan.py behavior.
    # The hairline points were drawn on the centered head, so the test harness
    # must center the head the same way for coordinates to match.
    print("\n--- Step 1c: Center head at origin ---")
    center_on_geometry(head)

    # Step 2: Load hairline config (already in mm, centered coordinate space)
    print("\n--- Step 2: Load hairline config ---")
    hairline_path = os.path.abspath(args.hairline_config)
    if not os.path.exists(hairline_path):
        raise FileNotFoundError(f"Hairline config not found: {hairline_path}")
    with open(hairline_path) as f:
        hairline_json_str = f.read()

    # Hairline points were drawn on the already-scaled, already-centered head
    # in Blender (after op_import_scan.py processed it). They are already in
    # the correct mm coordinate space — do NOT rescale them.
    pts_loaded = json.loads(hairline_json_str)
    print(f"  Loaded {len(pts_loaded)} hairline points (already in mm)")
    xs = [p[0] for p in pts_loaded]
    ys = [p[1] for p in pts_loaded]
    zs = [p[2] for p in pts_loaded]
    print(f"    Hairline BBox: X=[{min(xs):.1f}, {max(xs):.1f}] "
          f"Y=[{min(ys):.1f}, {max(ys):.1f}] "
          f"Z=[{min(zs):.1f}, {max(zs):.1f}]")

    # Step 3: Enable add-on and configure
    print("\n--- Step 3: Enable add-on ---")
    enable_addon()

    print("\n--- Step 4: Configure properties ---")
    configure_props(args, hairline_json_str)

    # Step 4: Run generation
    print("\n--- Step 5: Generate wig base ---")
    gen_start = time.time()
    shell = run_generation()
    gen_time = time.time() - gen_start
    print(f"  Generation time: {gen_time:.1f}s")

    if not shell:
        print("ERROR: No shell generated!")
        sys.exit(1)

    # Step 5: Compute metrics
    print("\n--- Step 6: Compute metrics ---")
    # Re-import head for metrics (it was deleted during generation as shrink target)
    # The head might still be in scene if generation preserved it
    head_in_scene = None
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj != shell:
            head_in_scene = obj
            break

    if not head_in_scene:
        # Re-import for rendering (scale to mm and center, matching op_import_scan)
        head_in_scene = import_head(args.head_model)
        if unit_scale != 1.0:
            apply_unit_scale(head_in_scene, unit_scale)
        center_on_geometry(head_in_scene)

    metrics = compute_metrics(shell, head_in_scene)
    metrics["generation_time_seconds"] = round(gen_time, 2)
    metrics["shell_mode"] = args.shell_mode

    # Print metrics
    print(f"  Vertices: {metrics['vertex_count']:,}")
    print(f"  Faces: {metrics['face_count']:,}")
    print(f"  Dimensions: {metrics['dimensions']['width']:.1f} x "
          f"{metrics['dimensions']['depth']:.1f} x "
          f"{metrics['dimensions']['height']:.1f} mm")
    print(f"  Manifold: {metrics['is_manifold']}")
    print(f"  Boundary edges: {metrics['boundary_edges']}")
    print(f"  Connected components: {metrics.get('connected_components', 'N/A')}")
    print(f"  Loose vertices: {metrics['loose_vertices']}")

    # Save metrics
    metrics_path = os.path.join(os.path.abspath(args.output_dir), "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  Saved: {metrics_path}")

    # Step 6: Export mesh
    print("\n--- Step 7: Export mesh ---")
    export_mesh(shell, args.output_dir)

    # Step 7: Render (with head + shell only for each angle)
    if not args.skip_render:
        print("\n--- Step 8: Render multi-angle views ---")
        print("  (rendering each angle WITH head and SHELL ONLY)")
        cam, center, cam_dist = setup_camera_and_lights(shell)
        render_angles(cam, center, cam_dist, args.render_dir, args.resolution,
                      head_obj=head_in_scene)

        # Step 8b: Create tiled overview image
        print("\n--- Step 9: Create tiled overview ---")
        tile_path = args.tile_output if args.tile_output else os.path.join(
            os.path.abspath(args.render_dir), "tiled_overview.png"
        )
        label = args.test_label if args.test_label else os.path.basename(
            os.path.abspath(args.render_dir)
        )
        create_tiled_image(args.render_dir, tile_path, test_label=label)
    else:
        print("\n--- Step 8: Rendering skipped ---")

    total_time = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"DONE in {total_time:.1f}s")
    print(f"  Renders: {os.path.abspath(args.render_dir)}")
    print(f"  Output:  {os.path.abspath(args.output_dir)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
