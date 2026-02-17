"""Generate a helmet wig base shell from an imported head scan mesh.

Pipeline:
1. Duplicate the scan object as a working copy
2. Clean the mesh (remove doubles, fix normals, delete loose geometry)
3. Voxel remesh for a clean, uniform topology (critical for scan data)
4. Smooth to remove remesh blockiness
5. Bisect to cut the bottom (edge ratio controls how much to keep)
6. Apply clearance offset via vertex normal displacement
7. Apply shell thickness (Solidify modifier)
8. Add rim band reinforcement along the bottom edge
9. Recalculate normals

The scan should already be in mm and centered (handled by the import operator).
"""

import bpy
import bmesh
from mathutils import Vector


class HWG_OT_GenerateBase(bpy.types.Operator):
    """Generate helmet wig base from the selected head scan mesh."""

    bl_idname = "hwg.generate_base"
    bl_label = "Generate Helmet Base"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hwg
        src = props.scan_object

        if not src or src.type != 'MESH':
            self.report({'ERROR'}, "Select a scan mesh object first.")
            return {'CANCELLED'}

        # --- Duplicate working copy ---
        work = src.copy()
        work.data = src.data.copy()
        work.name = f"{src.name}_HELMET_BASE"
        context.collection.objects.link(work)

        # Deselect all, select and activate working copy
        bpy.ops.object.select_all(action='DESELECT')
        work.select_set(True)
        context.view_layer.objects.active = work

        # --- Step 1: Clean the raw scan mesh ---
        # Merge doubles, remove loose geometry, fix normals, and
        # fill boundary holes so the mesh is watertight before remesh.
        self._clean_mesh(work)

        # --- Step 2: Voxel remesh for uniform topology ---
        # Raw scan meshes have inconsistent topology, holes, and
        # non-manifold edges. Voxel remesh creates a clean, watertight
        # mesh that Solidify can work with reliably.
        # Voxel size of 1.5mm gives good detail while smoothing out
        # scan noise. Adjust if needed for very detailed/coarse scans.
        work.data.remesh_voxel_size = 1.5  # mm
        work.data.use_remesh_fix_poles = True
        work.data.use_remesh_preserve_volume = True
        with bpy.context.temp_override(object=work, active_object=work):
            bpy.ops.object.voxel_remesh()

        # --- Step 3: Smooth to remove remesh blockiness ---
        mod_smooth = work.modifiers.new("HWG_Smooth", 'SMOOTH')
        mod_smooth.factor = 0.5
        mod_smooth.iterations = 5
        with bpy.context.temp_override(object=work, active_object=work):
            bpy.ops.object.modifier_apply(modifier=mod_smooth.name)

        # --- Compute bounding box for edge cut ---
        bbox = [work.matrix_world @ Vector(corner) for corner in work.bound_box]
        z_vals = [v.z for v in bbox]
        z_min, z_max = min(z_vals), max(z_vals)
        height = max(0.001, z_max - z_min)
        edge_z = z_min + height * props.edge_ratio

        # --- Step 4: Cut bottom (remove below edge_z) ---
        with bpy.context.temp_override(
            object=work, active_object=work, selected_objects=[work]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.bisect(
                plane_co=(0, 0, edge_z),
                plane_no=(0, 0, 1),
                clear_inner=True,
                clear_outer=False,
                use_fill=False,  # leave open — we want a shell, not a solid
            )
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 5: Recalc normals before offset/solidify ---
        # Critical: normals must be consistent and outward-facing for
        # both vertex normal offset and Solidify to work correctly.
        with bpy.context.temp_override(
            object=work, active_object=work, selected_objects=[work]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Step 6: Clearance offset via vertex normals ---
        # Push every vertex outward along its normal by clearance amount.
        # This is more reliable than Solidify offset=1 on scan meshes.
        clearance_mm = props.clearance_mm
        if clearance_mm > 0:
            self._offset_along_normals(work, clearance_mm)

        # --- Step 7: Shell thickness ---
        # Use Solidify to create the shell wall. Key settings:
        # - offset=-1: original surface becomes the OUTER wall; a second
        #   surface is created inward by thickness amount. Since we already
        #   pushed the mesh outward by clearance, the inner wall of the
        #   shell sits at clearance distance from the head, and the outer
        #   wall sits at clearance + thickness.
        # - use_even_offset=False: MUST be off — even offset explodes on
        #   open meshes with boundary edges from the bisect cut
        # - use_rim=True: closes the shell along the open bottom edge
        thickness_mm = props.thickness_mm
        mod_shell = work.modifiers.new("HWG_Shell", 'SOLIDIFY')
        mod_shell.thickness = thickness_mm
        mod_shell.offset = -1.0
        mod_shell.use_rim = True
        mod_shell.use_rim_only = False
        mod_shell.use_even_offset = False
        with bpy.context.temp_override(object=work, active_object=work):
            bpy.ops.object.modifier_apply(modifier=mod_shell.name)

        # --- Step 8: Rim band reinforcement ---
        rim_height_mm = props.rim_height_mm
        if rim_height_mm > 0:
            self._add_rim_band(work, edge_z, rim_height_mm)

        # --- Step 9: Final normals recalc ---
        with bpy.context.temp_override(
            object=work, active_object=work, selected_objects=[work]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        vert_count = len(work.data.vertices)
        self.report(
            {'INFO'},
            f"Generated: {work.name} ({vert_count:,} verts, "
            f"clearance={clearance_mm}mm, thickness={thickness_mm}mm, "
            f"rim={rim_height_mm}mm)",
        )
        return {'FINISHED'}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clean_mesh(self, obj):
        """Clean a raw scan mesh and make it watertight.

        Steps: merge doubles, remove loose geometry, fix normals,
        fill all boundary holes (open bottom of head scans, etc.)
        so the voxel remesh gets a closed input.
        """
        with bpy.context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.mode_set(mode='EDIT')

            bm = bmesh.from_edit_mesh(obj.data)

            # Remove duplicate vertices (within 0.1mm)
            bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.1)

            # Remove loose vertices and edges (not part of any face)
            loose_verts = [v for v in bm.verts if not v.link_faces]
            if loose_verts:
                bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

            loose_edges = [e for e in bm.edges if not e.link_faces]
            if loose_edges:
                bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

            # Fix normals
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

            bmesh.update_edit_mesh(obj.data)

            # Fill all boundary holes (open bottom of scan, etc.)
            # This makes the mesh watertight so voxel remesh works cleanly.
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(
                extend=False,
                use_wire=False,
                use_boundary=True,
                use_multi_face=False,
                use_non_contiguous=False,
                use_verts=False,
            )
            bpy.ops.mesh.fill_holes(sides=0)  # 0 = fill all regardless of size

            bpy.ops.object.mode_set(mode='OBJECT')

    def _offset_along_normals(self, obj, distance):
        """Push every vertex outward along its normal by distance (mm).

        More reliable than Solidify offset=1 for scan meshes because
        it doesn't depend on face connectivity or manifold topology.
        """
        me = obj.data
        me.calc_normals_split()

        bm = bmesh.new()
        bm.from_mesh(me)
        bm.verts.ensure_lookup_table()

        for v in bm.verts:
            v.co += v.normal * distance

        bm.to_mesh(me)
        bm.free()
        me.update()

    def _add_rim_band(self, obj, edge_z, rim_height_mm):
        """Extrude the bottom boundary edge downward to create a rim band."""
        with bpy.context.temp_override(
            object=obj, active_object=obj, selected_objects=[obj]
        ):
            bpy.ops.object.mode_set(mode='EDIT')

            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            # Select boundary edges (the open bottom edge of the shell)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(
                extend=False,
                use_wire=False,
                use_boundary=True,
                use_multi_face=False,
                use_non_contiguous=False,
                use_verts=False,
            )

            # Extrude downward to create the rim band
            bpy.ops.mesh.extrude_region_move(
                TRANSFORM_OT_translate={
                    "value": (0, 0, -rim_height_mm),
                    "orient_type": 'GLOBAL',
                }
            )

            bpy.ops.object.mode_set(mode='OBJECT')
