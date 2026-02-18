"""Generate a helmet wig base shell from an imported head scan mesh.

Pipeline (Shrinkwrap approach):
1. Prepare scan target: clean, fill holes, voxel remesh, smooth
2. Trim the scan target:
   - HELMET mode: flat bisect at edge_ratio height
   - WIG_CAP mode: flood-fill trim along user-drawn hairline contour
3. Create a UV sphere dome sized to the trimmed head
4. Shrinkwrap the dome onto the trimmed scan (OUTSIDE + clearance)
5. Hairline contour trim on the Shrinkwrapped dome (WIG_CAP only)
6. Smooth to clean up Shrinkwrap artifacts
7. Solidify for shell wall thickness
8. Optional rim band
9. Recalculate normals, clean up target

Key ordering constraints:
- Hairline trim (step 5) must be IMMEDIATELY after Shrinkwrap (step 4)
  so the dome edge doesn't wrap onto the face below the hairline.
- Hairline trim must be BEFORE Solidify (step 7) because flood-fill
  barrier detection breaks on double-walled solidified geometry.

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

        # --- Step 1b: Pre-smooth the hairline path ---
        # Run Laplacian smoothing on the stored hairline points to ensure
        # a clean organic curve with no kinks or ear-crossing segments.
        hairline_json = props.hairline_points_json
        if props.shell_mode == 'WIG_CAP' and hairline_json:
            hairline_json = self._smooth_hairline_path(hairline_json, scan)

        # --- Step 2: Trim the scan target ---
        bbox_full = [target.matrix_world @ Vector(c) for c in target.bound_box]
        z_min_full = min(v.z for v in bbox_full)
        z_max_full = max(v.z for v in bbox_full)
        height_full = max(0.001, z_max_full - z_min_full)

        if props.shell_mode == 'WIG_CAP' and hairline_json:
            # Contoured trim along user-drawn hairline
            # Don't fill — a flat cap would make Shrinkwrap conform to it
            self._hairline_trim(target, hairline_json, fill=False)
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

        # Trim the dome — rough cut so the sphere doesn't wrap to the full
        # head. WIG_CAP uses a generous flat cut below the lowest hairline
        # point; HELMET uses edge_ratio.
        if props.shell_mode == 'WIG_CAP' and hairline_json:
            hairline_pts = json.loads(hairline_json)
            min_hairline_z = min(p[2] for p in hairline_pts)
            # Small margin below lowest hairline point. Keep this tight
            # (5mm) to prevent dome vertices from wrapping to the jaw/
            # underside of the scan during Shrinkwrap. The precise
            # contour trim happens after Shrinkwrap.
            dome_cut_z = min_hairline_z - 5.0
            with bpy.context.temp_override(
                object=dome, active_object=dome, selected_objects=[dome]
            ):
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.bisect(
                    plane_co=(0, 0, dome_cut_z),
                    plane_no=(0, 0, 1),
                    clear_inner=True,
                    clear_outer=False,
                    use_fill=False,
                )
                bpy.ops.object.mode_set(mode='OBJECT')
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
                    use_fill=False,
                )
                bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 4: Shrinkwrap onto trimmed scan ---
        clearance_mm = props.clearance_mm

        mod_shrink = dome.modifiers.new("HWG_Shrinkwrap", 'SHRINKWRAP')
        mod_shrink.wrap_method = 'NEAREST_SURFACEPOINT'
        mod_shrink.wrap_mode = 'OUTSIDE_SURFACE'
        mod_shrink.target = target
        mod_shrink.offset = clearance_mm
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_shrink.name)

        # --- Step 5: Hairline contour trim (immediately after Shrinkwrap) ---
        # Now the dome vertices sit on the scan surface + clearance, so the
        # flood-fill barrier (8mm) will find dome vertices near the hairline
        # points. Trimming here — before any smoothing — prevents the bottom
        # edge from wrapping onto the face below the hairline.
        if props.shell_mode == 'WIG_CAP' and hairline_json:
            self._hairline_trim(dome, hairline_json, fill=False)

        # --- Step 6: Smooth (very light — just remove faceting) ---
        mod_smooth2 = dome.modifiers.new("HWG_Smooth", 'SMOOTH')
        mod_smooth2.factor = 0.5
        mod_smooth2.iterations = 4
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_smooth2.name)

        # --- Step 7: Solidify ---
        thickness_mm = props.thickness_mm

        mod_shell = dome.modifiers.new("HWG_Shell", 'SOLIDIFY')
        mod_shell.thickness = thickness_mm
        mod_shell.offset = -1.0  # grow outward
        mod_shell.use_rim = True
        mod_shell.use_rim_only = False
        mod_shell.use_even_offset = False
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_shell.name)

        # --- Step 8: Optional rim band ---
        rim_height_mm = props.rim_height_mm
        if rim_height_mm > 0:
            self._add_rim_band(dome, rim_height_mm)

        # --- Step 9: Final cleanup + normals ---
        with bpy.context.temp_override(
            object=dome, active_object=dome, selected_objects=[dome]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')

            # Merge overlapping verts from Solidify edge artifacts
            bpy.ops.mesh.remove_doubles(threshold=0.1)

            # Clean up loose geometry
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_loose()
            bpy.ops.mesh.delete(type='VERT')

            # Final normals
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 10: Clean up ---
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

    def _smooth_hairline_path(self, hairline_json, scan_obj):
        """Pre-smooth the hairline path for clean organic trimming.

        Runs Laplacian smoothing on the stored hairline points to remove
        kinks, sharp angles, and concavity segments (e.g. ear crossings).
        Points that dip inward relative to their neighbors (concavities)
        are pulled outward to the interpolated path.

        Args:
            hairline_json: JSON string of [[x,y,z], ...] hairline points.
            scan_obj: the scan mesh object (for bounding box center).

        Returns:
            JSON string of smoothed [[x,y,z], ...] points.
        """
        pts_raw = json.loads(hairline_json)
        if len(pts_raw) < 4:
            return hairline_json

        pts = [Vector(p) for p in pts_raw]

        # --- Concavity filter (ears) ---
        # Compute head center from scan bounding box
        bbox = [scan_obj.matrix_world @ Vector(c) for c in scan_obj.bound_box]
        center = sum(bbox, Vector()) / 8.0

        window = 4
        for _pass in range(3):  # multiple passes to catch stubborn dips
            new_pts = [pts[0].copy()]
            for i in range(1, len(pts) - 1):
                dist = (pts[i] - center).length
                # Average neighbor distance
                neighbors = []
                for j in range(max(0, i - window), min(len(pts), i + window + 1)):
                    if j != i:
                        neighbors.append((pts[j] - center).length)
                avg_dist = sum(neighbors) / len(neighbors) if neighbors else dist

                if dist < avg_dist - 2.0:
                    # Point dips inward — replace with neighbor interpolation
                    prev_pt = pts[max(0, i - 1)]
                    next_pt = pts[min(len(pts) - 1, i + 1)]
                    new_pts.append((prev_pt + next_pt) / 2.0)
                else:
                    new_pts.append(pts[i].copy())
            new_pts.append(pts[-1].copy())
            pts = new_pts

        # --- Laplacian smoothing (30 passes) ---
        # Symmetric neighbor averaging to remove kinks and create a
        # flowing organic curve.
        for _ in range(30):
            smoothed = [pts[0].copy()]
            for i in range(1, len(pts) - 1):
                avg = (pts[i - 1] + pts[i + 1]) / 2.0
                pt = pts[i].lerp(avg, 0.5)
                smoothed.append(pt)
            smoothed.append(pts[-1].copy())
            pts = smoothed

        return json.dumps([[p.x, p.y, p.z] for p in pts])

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

        Uses a flood-fill approach on the mesh topology:
        1. Find the closest mesh vertex to each hairline point — these
           form a "barrier band" on the mesh surface.
        2. Find the topmost vertex (crown) as the seed for the keep region.
        3. Flood-fill from the crown through mesh edges, stopping at
           barrier vertices — everything reached is "above" the hairline.
        4. Delete all vertices NOT reached by the flood.
        5. Smooth the boundary edge via vertex group + Smooth modifier.

        This is topology-aware and works regardless of head orientation,
        ear geometry, or forehead curvature.

        Args:
            obj: Blender mesh object to trim.
            hairline_json: JSON string of [[x,y,z], ...] hairline points.
            fill: If True, fill boundary holes after trimming (for
                  Shrinkwrap target only — do NOT fill the dome).
        """
        from collections import deque

        pts_raw = json.loads(hairline_json)
        if len(pts_raw) < 3:
            return

        hairline = [Vector(p) for p in pts_raw]

        vg_name = "_hwg_edge_smooth"

        with bpy.context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()

            mat = obj.matrix_world

            # --- Step 1: Find barrier vertices ---
            # For each hairline point, find the closest mesh vertex.
            # Use a distance threshold to create a band (not just single verts)
            # so the barrier is thick enough to stop the flood.
            # The radius must be large enough to catch vertices on the dome,
            # which sits clearance_mm (typically 3.5mm) above the scan
            # surface where the hairline points were drawn.
            barrier = set()
            barrier_radius = 8.0  # mm — accounts for clearance offset + margin

            for hp in hairline:
                for v in bm.verts:
                    wco = mat @ v.co
                    dist = (wco - hp).length
                    if dist < barrier_radius:
                        barrier.add(v.index)

            if not barrier:
                # No barrier found — hairline points too far from mesh.
                # Skip trimming entirely.
                bmesh.update_edit_mesh(obj.data)
                bpy.ops.object.mode_set(mode='OBJECT')
                return

            # --- Step 2: Find the crown (topmost vertex) as flood seed ---
            crown_vert = max(bm.verts, key=lambda v: (mat @ v.co).z)

            # --- Step 3: Flood-fill from crown, stopping at barrier ---
            keep = set()
            queue = deque()

            if crown_vert.index not in barrier:
                queue.append(crown_vert.index)
                keep.add(crown_vert.index)

            while queue:
                vi = queue.popleft()
                v = bm.verts[vi]
                for edge in v.link_edges:
                    other = edge.other_vert(v)
                    oi = other.index
                    if oi not in keep and oi not in barrier:
                        keep.add(oi)
                        queue.append(oi)

            # Also keep barrier verts (they sit ON the hairline)
            keep.update(barrier)

            # --- Step 4: Delete everything not reached ---
            verts_to_delete = [v for v in bm.verts if v.index not in keep]

            if not verts_to_delete:
                # Nothing to trim
                bmesh.update_edit_mesh(obj.data)
                bpy.ops.object.mode_set(mode='OBJECT')
                return

            bmesh.ops.delete(bm, geom=verts_to_delete, context='VERTS')

            # --- Step 4b: Keep only the largest connected component ---
            # The barrier band around ears can create small disconnected
            # islands. Flood-fill from the topmost remaining vertex to
            # find the main shell, delete everything else.
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            if bm.verts:
                crown2 = max(bm.verts, key=lambda v: (mat @ v.co).z)
                main_component = set()
                q2 = deque([crown2.index])
                main_component.add(crown2.index)
                while q2:
                    vi = q2.popleft()
                    for edge in bm.verts[vi].link_edges:
                        oi = edge.other_vert(bm.verts[vi]).index
                        if oi not in main_component:
                            main_component.add(oi)
                            q2.append(oi)

                fragments = [v for v in bm.verts if v.index not in main_component]
                if fragments:
                    bmesh.ops.delete(bm, geom=fragments, context='VERTS')

            # --- Step 4c: Basic cleanup ---
            bm.verts.ensure_lookup_table()
            loose_verts = [v for v in bm.verts if not v.link_faces]
            if loose_verts:
                bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

            bm.edges.ensure_lookup_table()
            loose_edges = [e for e in bm.edges if not e.link_faces]
            if loose_edges:
                bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

            bm.verts.ensure_lookup_table()
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.3)

            bmesh.update_edit_mesh(obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 5: Smooth boundary edge via vertex group + modifier ---
        # Create vertex group in object mode to avoid stale references.
        # Use a wide smooth region and aggressive smoothing
        # so Solidify's rim faces form a clean, flat bottom edge.
        vg = obj.vertex_groups.get(vg_name)
        if vg:
            obj.vertex_groups.remove(vg)
        vg = obj.vertex_groups.new(name=vg_name)
        vg_idx = vg.index

        with bpy.context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()

            # Find boundary verts (verts on open edges)
            boundary_verts = set()
            for v in bm.verts:
                for e in v.link_edges:
                    if e.is_boundary:
                        boundary_verts.add(v.index)
                        break

            # Grow selection rings for smooth region — use gradient weights
            # so the boundary gets full smoothing and it tapers off further in.
            # This prevents a hard transition between smoothed and unsmoothed.
            ring_count = 20
            vert_ring = {}  # vert index -> ring number (0 = boundary)
            for vi in boundary_verts:
                vert_ring[vi] = 0

            current_ring = set(boundary_verts)
            for ring in range(1, ring_count + 1):
                next_ring = set()
                for vi in current_ring:
                    v = bm.verts[vi]
                    for e in v.link_edges:
                        oi = e.other_vert(v).index
                        if oi not in vert_ring:
                            vert_ring[oi] = ring
                            next_ring.add(oi)
                current_ring = next_ring

            # Assign to vertex group via deform layer with gradient weights
            deform_layer = bm.verts.layers.deform.verify()
            for v in bm.verts:
                if v.index in vert_ring:
                    ring = vert_ring[v.index]
                    # Weight: 1.0 at boundary, tapering to 0.0 at outermost ring
                    weight = 1.0 - (ring / (ring_count + 1))
                    v[deform_layer][vg_idx] = weight

            bmesh.update_edit_mesh(obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

        # Apply multiple Smooth passes for a very clean edge.
        # Two passes: first a strong pass to iron out bumps, then a
        # lighter pass to feather the transition. This forces any
        # hand-drawn hairline abnormalities into a smooth curve.
        for factor, iters in [(1.0, 80), (0.5, 40)]:
            mod_smooth = obj.modifiers.new("HWG_EdgeSmooth", 'SMOOTH')
            mod_smooth.factor = factor
            mod_smooth.iterations = iters
            mod_smooth.vertex_group = vg_name
            with bpy.context.temp_override(object=obj, active_object=obj):
                bpy.ops.object.modifier_apply(modifier=mod_smooth.name)

        # Clean up the temp vertex group — re-fetch by name since the
        # original reference may be stale after modifier_apply
        vg_cleanup = obj.vertex_groups.get(vg_name)
        if vg_cleanup:
            obj.vertex_groups.remove(vg_cleanup)

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
