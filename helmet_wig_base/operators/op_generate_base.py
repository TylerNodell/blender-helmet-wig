"""Generate a helmet wig base shell from an imported head scan mesh.

Pipeline (Shrinkwrap approach):
1. Prepare scan target: clean, fill holes, voxel remesh, smooth
2. Bisect the scan target to remove neck/shoulders
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
            self.report({'ERROR'}, "Select a scan mesh object first.")
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

        # --- Step 2: Bisect the scan target to remove neck/shoulders ---
        # Compute edge_z from the FULL scan bounding box, then cut
        # the target so Shrinkwrap only sees the head portion.
        bbox_full = [target.matrix_world @ Vector(c) for c in target.bound_box]
        z_min_full = min(v.z for v in bbox_full)
        z_max_full = max(v.z for v in bbox_full)
        height_full = max(0.001, z_max_full - z_min_full)
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
                use_fill=True,  # fill the cut so it's watertight for Shrinkwrap
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
            segments=64,
            ring_count=32,
            radius=radius,
            location=(center_x, center_y, center_z),
        )
        dome = context.active_object
        dome.name = f"{scan.name}_HELMET_BASE"

        # Bisect the dome at the same height
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
        clearance_mm = props.clearance_mm
        mod_shrink = dome.modifiers.new("HWG_Shrinkwrap", 'SHRINKWRAP')
        mod_shrink.wrap_method = 'NEAREST_SURFACEPOINT'
        mod_shrink.wrap_mode = 'OUTSIDE_SURFACE'
        mod_shrink.target = target
        mod_shrink.offset = clearance_mm
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_shrink.name)

        # --- Step 5: Smooth ---
        mod_smooth2 = dome.modifiers.new("HWG_Smooth", 'SMOOTH')
        mod_smooth2.factor = 0.5
        mod_smooth2.iterations = 3
        with bpy.context.temp_override(object=dome, active_object=dome):
            bpy.ops.object.modifier_apply(modifier=mod_smooth2.name)

        # --- Step 6: Solidify ---
        thickness_mm = props.thickness_mm
        mod_shell = dome.modifiers.new("HWG_Shell", 'SOLIDIFY')
        mod_shell.thickness = thickness_mm
        mod_shell.offset = -1.0  # grow outward
        mod_shell.use_rim = True
        mod_shell.use_rim_only = False
        mod_shell.use_even_offset = True
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
