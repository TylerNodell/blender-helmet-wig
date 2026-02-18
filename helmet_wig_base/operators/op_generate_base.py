"""Generate a helmet wig base shell from an imported head scan mesh.

Pipeline (Shrinkwrap approach):
1. Prepare scan target: clean, fill holes, voxel remesh, smooth
2. Trim the scan target:
   - HELMET mode: flat bisect at edge_ratio height
   - WIG_CAP mode: per-vertex trim along user-drawn hairline contour
3. Create a UV sphere dome sized to the trimmed head
4. Shrinkwrap the dome onto the trimmed scan (OUTSIDE + clearance)
5. Smooth to clean up Shrinkwrap artifacts
6. Solidify for shell wall thickness
7. Optional rim band
8. Recalculate normals, clean up target

The Shrinkwrap approach starts with clean UV sphere topology and
projects it onto the scan, avoiding all issues with scan mesh quality.
"""

import bpy
import bmesh
import json
import math
from mathutils import Vector


class HWG_OT_GenerateBase(bpy.types.Operator):
    """Generate helmet wig base from the selected head scan mesh."""

    bl_idname = "hwg.generate_base"
    bl_label = "Generate Helmet Base"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hwg
        scan = props.scan_object

        if not scan or scan.type != 'MESH':
            self.report({'ERROR'}, "Set a scan mesh object first.")
            return {'CANCELLED'}

        if props.shell_mode == 'WIG_CAP' and not props.hairline_points_json:
            self.report(
                {'ERROR'},
                "Draw a hairline first (Draw Hairline button) or switch to Helmet mode.",
            )
            return {'CANCELLED'}

        # --- Step 1: Prepare clean scan target ---
        target = scan.copy()
        target.data = scan.data.copy()
        target.name = f"{scan.name}_SHRINK_TARGET"
        context.collection.objects.link(target)

        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target

        self._clean_mesh(target)

        # Voxel remesh
        target.data.remesh_voxel_size = 1.5
        target.data.use_remesh_fix_poles = True
        target.data.use_remesh_preserve_volume = True
        with bpy.context.temp_override(object=target, active_object=target):
            bpy.ops.object.voxel_remesh()

        # Smooth
        mod_smooth = target.modifiers.new("HWG_Smooth", 'SMOOTH')
        mod_smooth.factor = 0.5
        mod_smooth.iterations = 5
        with bpy.context.temp_override(object=target, active_object=target):
            bpy.ops.object.modifier_apply(modifier=mod_smooth.name)

        # --- Step 2: Trim the scan target ---
        bbox_full = [target.matrix_world @ Vector(c) for c in target.bound_box]
        z_min_full = min(v.z for v in bbox_full)
        z_max_full = max(v.z for v in bbox_full)
        height_full = max(0.001, z_max_full - z_min_full)

        if props.shell_mode == 'WIG_CAP' and props.hairline_points_json:
            # Contoured trim along user-drawn hairline
            self._hairline_trim(target, props.hairline_points_json)
        else:
            # Flat bisect at edge_ratio height (HELMET mode or no hairline)
            edge_z = z_min_full + height_full * props.edge_ratio
            with bpy.context.temp_override(
                object=target, active_object=target, selected_objects=[target]
            ):
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.bisect(
                    plane_co=(0, 0, edge_z),
                    plane_no=(0, 0, 1),
                    clear_inner=True,
                    clear_outer=False,
                    use_fill=True,
                )
                bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 3: Create UV sphere dome sized to the trimmed head ---
        bbox = [target.matrix_world @ Vector(c) for c in target.bound_box]
        xs = [v.x for v in bbox]
        ys = [v.y for v in bbox]
        zs = [v.z for v in bbox]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        z_min, z_max = min(zs), max(zs)

        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0
        center_z = (z_min + z_max) / 2.0

        # Sphere radius: just big enough to enclose the trimmed head
        half_w = (x_max - x_min) / 2.0
        half_d = (y_max - y_min) / 2.0
        half_h = (z_max - z_min) / 2.0
        radius = max(half_w, half_d, half_h) * 1.2

        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=128,
            ring_count=64,
            radius=radius,
            location=(center_x, center_y, center_z),
        )
        dome = context.active_object
        dome.name = f"{scan.name}_HELMET_BASE"

        # Trim the dome at the same contour
        if props.shell_mode == 'WIG_CAP' and props.hairline_points_json:
            self._hairline_trim(dome, props.hairline_points_json, fill=False)
        else:
            edge_z = z_min_full + height_full * props.edge_ratio
            with bpy.context.temp_override(
                object=dome, active_object=dome, selected_objects=[dome]
            ):
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.bisect(
                    plane_co=(0, 0, edge_z),
                    plane_no=(0, 0, 1),
                    clear_inner=True,
                    clear_outer=False,
                    use_fill=False,  # leave open for shell
                )
                bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 4: Shrinkwrap onto trimmed scan ---
        # All values are in Blender units, which should be mm after
        # the import operator scales the scan. If the scan bbox is in
        # the 15-25 range, it's likely in cm — warn the user.
        clearance_mm = props.clearance_mm

        mod_shrink = dome.modifiers.new("HWG_Shrinkwrap", 'SHRINKWRAP')
        mod_shrink.wrap_method = 'NEAREST_SURFACEPOINT'
        mod_shrink.wrap_mode = 'OUTSIDE_SURFACE'
        mod_shrink.target = target
        mod_shrink.offset = clearance_mm
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_shrink.name)

        # --- Step 5: Smooth (very light — just remove faceting) ---
        mod_smooth2 = dome.modifiers.new("HWG_Smooth", 'SMOOTH')
        mod_smooth2.factor = 0.5
        mod_smooth2.iterations = 4
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_smooth2.name)

        # --- Step 6: Solidify ---
        thickness_mm = props.thickness_mm

        mod_shell = dome.modifiers.new("HWG_Shell", 'SOLIDIFY')
        mod_shell.thickness = thickness_mm
        mod_shell.offset = -1.0  # grow outward
        mod_shell.use_rim = True
        mod_shell.use_rim_only = False
        mod_shell.use_even_offset = False
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_shell.name)

        # --- Step 7: Optional rim band ---
        rim_height_mm = props.rim_height_mm
        if rim_height_mm > 0:
            self._add_rim_band(dome, rim_height_mm)

        # --- Step 8: Final normals ---
        with bpy.context.temp_override(
            object=dome, active_object=dome, selected_objects=[dome]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 9: Clean up ---
        bpy.data.objects.remove(target, do_unlink=True)

        bpy.ops.object.select_all(action='DESELECT')
        dome.select_set(True)
        context.view_layer.objects.active = dome

        # Warn if scan appears to be in wrong units
        bbox_check = [dome.matrix_world @ Vector(c) for c in dome.bound_box]
        max_dim = max(
            max(v.x for v in bbox_check) - min(v.x for v in bbox_check),
            max(v.y for v in bbox_check) - min(v.y for v in bbox_check),
            max(v.z for v in bbox_check) - min(v.z for v in bbox_check),
        )
        if max_dim < 50:
            self.report(
                {'WARNING'},
                f"Shell is only {max_dim:.1f} units wide — scan may be in cm, not mm. "
                f"Try reimporting with Scan Units set to Centimeters.",
            )

        vert_count = len(dome.data.vertices)
        self.report(
            {'INFO'},
            f"Generated: {dome.name} ({vert_count:,} verts, "
            f"clearance={clearance_mm}mm, thickness={thickness_mm}mm)",
        )
        return {'FINISHED'}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clean_mesh(self, obj):
        """Clean a raw scan mesh and make it watertight."""
        with bpy.context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.mode_set(mode='EDIT')

            bm = bmesh.from_edit_mesh(obj.data)
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.1)

            loose_verts = [v for v in bm.verts if not v.link_faces]
            if loose_verts:
                bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

            loose_edges = [e for e in bm.edges if not e.link_faces]
            if loose_edges:
                bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            bmesh.update_edit_mesh(obj.data)

            # Fill boundary holes
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(
                extend=False, use_wire=False, use_boundary=True,
                use_multi_face=False, use_non_contiguous=False, use_verts=False,
            )
            bpy.ops.mesh.fill_holes(sides=0)

            bpy.ops.object.mode_set(mode='OBJECT')

    def _hairline_trim(self, obj, hairline_json, fill=True):
        """Trim a mesh along a user-drawn hairline contour.

        Converts the hairline points to polar angle → Z height mapping,
        then deletes all vertices below their corresponding hairline Z.

        Args:
            obj: Blender mesh object to trim.
            hairline_json: JSON string of [[x,y,z], ...] hairline points.
            fill: If True, fill boundary holes after trimming.
        """
        pts_raw = json.loads(hairline_json)
        if len(pts_raw) < 3:
            return

        hairline = [Vector(p) for p in pts_raw]

        # Compute center XY from the hairline points themselves
        cx = sum(p.x for p in hairline) / len(hairline)
        cy = sum(p.y for p in hairline) / len(hairline)

        # Build angle → Z mapping from hairline points
        angle_z = []
        for p in hairline:
            angle = math.atan2(p.y - cy, p.x - cx)
            angle_z.append((angle, p.z))
        # Sort by angle for interpolation
        angle_z.sort(key=lambda a: a[0])

        def hairline_z_at_angle(theta):
            """Interpolate the hairline Z value at a given angle."""
            n = len(angle_z)
            if n == 0:
                return 0.0

            # Wrap theta into [-pi, pi]
            while theta > math.pi:
                theta -= 2 * math.pi
            while theta < -math.pi:
                theta += 2 * math.pi

            # Find the two bracketing samples
            for i in range(n):
                if angle_z[i][0] >= theta:
                    break
            else:
                i = 0  # wrap around

            i1 = i
            i0 = (i - 1) % n

            a0, z0 = angle_z[i0]
            a1, z1 = angle_z[i1]

            # Handle wrap-around
            da = a1 - a0
            if da < 0:
                da += 2 * math.pi
            dt = theta - a0
            if dt < 0:
                dt += 2 * math.pi

            if abs(da) < 1e-8:
                return z0

            t = dt / da
            return z0 + (z1 - z0) * t

        # Delete vertices below the hairline contour using bmesh
        with bpy.context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()

            verts_to_delete = []
            for v in bm.verts:
                world_co = obj.matrix_world @ v.co
                angle = math.atan2(world_co.y - cy, world_co.x - cx)
                threshold_z = hairline_z_at_angle(angle)
                if world_co.z < threshold_z:
                    verts_to_delete.append(v)

            if verts_to_delete:
                bmesh.ops.delete(bm, geom=verts_to_delete, context='VERTS')

            bmesh.update_edit_mesh(obj.data)

            if fill:
                # Fill boundary holes to make watertight for Shrinkwrap
                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.mesh.select_non_manifold(
                    extend=False, use_wire=False, use_boundary=True,
                    use_multi_face=False, use_non_contiguous=False,
                    use_verts=False,
                )
                bpy.ops.mesh.fill_holes(sides=0)

            bpy.ops.object.mode_set(mode='OBJECT')

    def _add_rim_band(self, obj, rim_height_mm):
        """Extrude the bottom boundary edge downward to create a rim band."""
        with bpy.context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.mode_set(mode='EDIT')

            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(
                extend=False, use_wire=False, use_boundary=True,
                use_multi_face=False, use_non_contiguous=False, use_verts=False,
            )

            bpy.ops.mesh.extrude_region_move(
                TRANSFORM_OT_translate={
                    "value": (0, 0, -rim_height_mm),
                    "orient_type": 'GLOBAL',
                }
            )

            bpy.ops.object.mode_set(mode='OBJECT')
