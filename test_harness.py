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
                        choices=["WIG_CAP", "HELMET"],
                        help="Shell generation mode")
    parser.add_argument("--clearance", type=float, default=None,
                        help="Clearance in mm (overrides default)")
    parser.add_argument("--thickness", type=float, default=None,
                        help="Shell thickness in mm (overrides default)")
    parser.add_argument("--resolution", default="1024x1024",
                        help="Render resolution WxH")
    parser.add_argument("--skip-render", action="store_true",
                        help="Skip rendering (just generate + export)")
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

    # 3-point lighting
    for name, loc, energy in [
        ("Key", (cam_dist * 0.8, -cam_dist * 0.6, cam_dist * 0.8), 500),
        ("Fill", (-cam_dist * 0.6, -cam_dist * 0.4, cam_dist * 0.3), 200),
        ("Rim", (-cam_dist * 0.2, cam_dist * 0.8, cam_dist * 0.6), 300),
    ]:
        light_data = bpy.data.lights.new(f"HWG_{name}", 'AREA')
        light_data.energy = energy
        light_data.size = max_dim * 0.5
        light_obj = bpy.data.objects.new(f"HWG_{name}", light_data)
        light_obj.location = Vector(loc) + center
        bpy.context.collection.objects.link(light_obj)

    # Shell material — semi-transparent blue so it's visible over the head
    shell_mat = bpy.data.materials.new("HWG_Shell_Mat")
    shell_mat.use_nodes = True
    nodes = shell_mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.2, 0.4, 0.8, 1.0)
        bsdf.inputs["Alpha"].default_value = 0.85
        bsdf.inputs["Roughness"].default_value = 0.3
    shell_mat.blend_method = 'BLEND' if hasattr(shell_mat, 'blend_method') else 'OPAQUE'
    shell_obj.data.materials.clear()
    shell_obj.data.materials.append(shell_mat)

    # Head material — light gray
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and obj != shell_obj:
            head_mat = bpy.data.materials.new("HWG_Head_Mat")
            head_mat.use_nodes = True
            h_nodes = head_mat.node_tree.nodes
            h_bsdf = h_nodes.get("Principled BSDF")
            if h_bsdf:
                h_bsdf.inputs["Base Color"].default_value = (0.75, 0.7, 0.68, 1.0)
                h_bsdf.inputs["Roughness"].default_value = 0.5
            obj.data.materials.clear()
            obj.data.materials.append(head_mat)

    return cam_obj, center, cam_dist


def render_angles(cam_obj, center, cam_dist, render_dir, resolution):
    """Render the scene from multiple angles."""
    w, h = [int(x) for x in resolution.split("x")]
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if bpy.app.version >= (4, 0, 0) else 'BLENDER_EEVEE'
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'

    # Camera angles: (name, azimuth_deg, elevation_deg)
    angles = [
        ("front", 0, 15),
        ("left", 90, 15),
        ("right", -90, 15),
        ("back", 180, 15),
        ("top", 0, 80),
        ("quarter_front_left", 45, 20),
        ("quarter_front_right", -45, 20),
        ("bottom", 180, -30),  # View from below to check for internal flaps
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

        # Render
        filepath = os.path.join(os.path.abspath(render_dir), f"{name}.png")
        scene.render.filepath = filepath
        bpy.ops.render.render(write_still=True)
        print(f"  Rendered: {name}.png")


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

    # Step 1: Clear and import
    print("\n--- Step 1: Import head model ---")
    clear_scene()
    head = import_head(args.head_model)

    # Step 2: Load hairline config
    print("\n--- Step 2: Load hairline config ---")
    hairline_path = os.path.abspath(args.hairline_config)
    if not os.path.exists(hairline_path):
        raise FileNotFoundError(f"Hairline config not found: {hairline_path}")
    with open(hairline_path) as f:
        hairline_json_str = f.read()

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
        # Re-import for rendering
        head_in_scene = import_head(args.head_model)

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

    # Step 7: Render
    if not args.skip_render:
        print("\n--- Step 8: Render multi-angle views ---")
        cam, center, cam_dist = setup_camera_and_lights(shell)
        render_angles(cam, center, cam_dist, args.render_dir, args.resolution)
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
