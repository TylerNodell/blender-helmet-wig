"""Generate synthetic hairline points on a head scan mesh.

Run inside Blender (headless or GUI):
  blender --background --python tests/generate_hairline.py -- \
    --head-model tests/fixtures/BaldGuy-LP_head.obj \
    --output tests/fixtures/hairline_default.json \
    --height-ratio 0.55

The hairline is created by:
1. Import the head mesh
2. Compute the bounding box
3. Slice the head at a configurable height ratio (0 = chin, 1 = crown)
4. Walk the boundary edge loop to extract ordered 3D points
5. Smooth and resample to even spacing
6. Export as JSON [[x,y,z], ...]
"""

import bpy
import bmesh
import json
import math
import sys
from collections import deque
from mathutils import Vector


def parse_args():
    """Parse CLI args after '--' separator."""
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    import argparse
    parser = argparse.ArgumentParser(description="Generate synthetic hairline")
    parser.add_argument("--head-model", required=True, help="Path to head OBJ/STL")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--height-ratio", type=float, default=0.55,
                        help="Height ratio for hairline (0=chin, 1=crown)")
    parser.add_argument("--offset-back", type=float, default=0.0,
                        help="Lower the hairline at the back (mm)")
    parser.add_argument("--offset-front", type=float, default=0.0,
                        help="Raise the hairline at the front (mm)")
    return parser.parse_args(argv)


def import_head(filepath):
    """Import a head mesh and return the object."""
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

    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj
    return obj


def generate_hairline(head_obj, height_ratio=0.55, offset_back=0.0, offset_front=0.0):
    """Generate hairline points by slicing the head at a height ratio.

    Returns list of Vector (world space) ordered around the head.
    """
    mat = head_obj.matrix_world
    bbox = [mat @ Vector(c) for c in head_obj.bound_box]
    z_min = min(v.z for v in bbox)
    z_max = max(v.z for v in bbox)
    height = z_max - z_min

    # Base cut height
    cut_z = z_min + height * height_ratio

    # Compute head center for angular sorting
    center_x = sum(v.x for v in bbox) / 8.0
    center_y = sum(v.y for v in bbox) / 8.0

    # Duplicate the head mesh to work on
    temp = head_obj.copy()
    temp.data = head_obj.data.copy()
    temp.name = "_hairline_temp"
    bpy.context.collection.objects.link(temp)
    bpy.context.view_layer.objects.active = temp
    temp.select_set(True)

    # Bisect at cut_z — keep upper half
    with bpy.context.temp_override(
        object=temp, active_object=temp, selected_objects=[temp]
    ):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(
            plane_co=(0, 0, cut_z),
            plane_no=(0, 0, 1),
            clear_inner=True,
            clear_outer=False,
            use_fill=False,
        )
        bpy.ops.object.mode_set(mode='OBJECT')

    # Extract boundary edge loop vertices
    bm = bmesh.new()
    bm.from_mesh(temp.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    mat_t = temp.matrix_world

    # Find boundary verts (on open edges)
    boundary_verts = []
    for v in bm.verts:
        for e in v.link_edges:
            if e.is_boundary:
                boundary_verts.append(v)
                break

    if not boundary_verts:
        print("WARNING: No boundary vertices found")
        bm.free()
        bpy.data.objects.remove(temp, do_unlink=True)
        return []

    # Order boundary verts by walking the edge loop
    ordered = []
    visited = set()
    current = boundary_verts[0]
    visited.add(current.index)
    ordered.append(mat_t @ current.co)

    for _ in range(len(boundary_verts) * 2):
        found_next = False
        for e in current.link_edges:
            if e.is_boundary:
                other = e.other_vert(current)
                if other.index not in visited:
                    visited.add(other.index)
                    ordered.append(mat_t @ other.co)
                    current = other
                    found_next = True
                    break
        if not found_next:
            break

    bm.free()
    bpy.data.objects.remove(temp, do_unlink=True)

    # Apply front/back offsets based on Y position
    # Front = positive Y (facing forward), Back = negative Y
    if offset_front != 0.0 or offset_back != 0.0:
        y_min = min(p.y for p in ordered)
        y_max = max(p.y for p in ordered)
        y_range = max(0.001, y_max - y_min)
        for i, p in enumerate(ordered):
            # Normalize Y: 0 = back, 1 = front
            t = (p.y - y_min) / y_range
            # Blend between back offset (low t) and front offset (high t)
            z_offset = offset_back * (1.0 - t) + offset_front * t
            ordered[i] = Vector((p.x, p.y, p.z + z_offset))

    # Sort by angle around head center for consistent ordering
    def angle_key(p):
        return math.atan2(p.y - center_y, p.x - center_x)
    ordered.sort(key=angle_key)

    # Resample to even spacing (3mm)
    if len(ordered) > 2:
        ordered = resample_points(ordered, spacing=3.0)

    return ordered


def resample_points(pts, spacing=3.0):
    """Resample a point list to even spacing."""
    if len(pts) < 2:
        return pts

    resampled = [pts[0].copy()]
    accum = 0.0
    for i in range(1, len(pts)):
        seg_len = (pts[i] - pts[i - 1]).length
        accum += seg_len
        if accum >= spacing:
            resampled.append(pts[i].copy())
            accum = 0.0
    if (resampled[-1] - pts[-1]).length > 0.1:
        resampled.append(pts[-1].copy())
    return resampled


def main():
    args = parse_args()

    # Clear scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Import head
    print(f"Importing head model: {args.head_model}")
    head = import_head(args.head_model)
    print(f"  Vertices: {len(head.data.vertices):,}")
    print(f"  Faces: {len(head.data.polygons):,}")

    # Generate hairline
    print(f"Generating hairline at height ratio {args.height_ratio}")
    points = generate_hairline(
        head,
        height_ratio=args.height_ratio,
        offset_back=args.offset_back,
        offset_front=args.offset_front,
    )
    print(f"  Generated {len(points)} hairline points")

    # Export
    pts_list = [[p.x, p.y, p.z] for p in points]
    with open(args.output, "w") as f:
        json.dump(pts_list, f, indent=2)
    print(f"  Saved to: {args.output}")

    # Also print bbox for reference
    mat = head.matrix_world
    bbox = [mat @ Vector(c) for c in head.bound_box]
    print(f"  Head bbox Z: {min(v.z for v in bbox):.1f} to {max(v.z for v in bbox):.1f}")


if __name__ == "__main__":
    main()
