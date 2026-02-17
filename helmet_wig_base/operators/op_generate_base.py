"""Generate a helmet wig base shell from an imported head scan mesh.

Pipeline:
1. Duplicate the scan object as a working copy
2. Bisect to cut the bottom (edge ratio controls how much to keep)
3. Fill holes from incomplete scans
4. Apply clearance offset (Solidify outward)
5. Apply shell thickness (Solidify inward)
6. Add rim band reinforcement along the bottom edge
7. Recalculate normals

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

        # --- Compute bounding box for edge cut ---
        bbox = [work.matrix_world @ Vector(corner) for corner in work.bound_box]
        z_vals = [v.z for v in bbox]
        z_min, z_max = min(z_vals), max(z_vals)
        height = max(0.001, z_max - z_min)
        edge_z = z_min + height * props.edge_ratio

        # --- Cut bottom (remove below edge_z) ---
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
                use_fill=True,
            )
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Hole filling (prevent solidify artifacts on incomplete scans) ---
        with bpy.context.temp_override(
            object=work, active_object=work, selected_objects=[work]
        ):
            bpy.ops.object.mode_set(mode='EDIT')

            me = work.data
            bm = bmesh.from_edit_mesh(me)

            # Select boundary edges (holes in the mesh)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(
                extend=False,
                use_wire=False,
                use_boundary=True,
                use_multi_face=False,
                use_non_contiguous=False,
                use_verts=False,
            )

            # Fill holes
            bpy.ops.mesh.edge_face_add()
            bpy.ops.mesh.fill_holes(sides=0)

            bmesh.update_edit_mesh(me)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Clearance offset (push surface outward) ---
        clearance_mm = props.clearance_mm
        if clearance_mm > 0:
            mod_clear = work.modifiers.new("HWG_Clearance", 'SOLIDIFY')
            mod_clear.thickness = clearance_mm
            mod_clear.offset = 1.0  # push outward only
            mod_clear.use_rim = False
            mod_clear.use_even_offset = True
            with bpy.context.temp_override(object=work, active_object=work):
                bpy.ops.object.modifier_apply(modifier=mod_clear.name)

        # --- Shell thickness ---
        thickness_mm = props.thickness_mm
        mod_shell = work.modifiers.new("HWG_Shell", 'SOLIDIFY')
        mod_shell.thickness = thickness_mm
        mod_shell.offset = -1.0  # grow outward from the offset surface
        mod_shell.use_rim = True
        mod_shell.use_rim_only = False
        mod_shell.use_even_offset = True
        with bpy.context.temp_override(object=work, active_object=work):
            bpy.ops.object.modifier_apply(modifier=mod_shell.name)

        # --- Rim band reinforcement ---
        rim_height_mm = props.rim_height_mm
        if rim_height_mm > 0:
            with bpy.context.temp_override(
                object=work, active_object=work, selected_objects=[work]
            ):
                bpy.ops.object.mode_set(mode='EDIT')

                me = work.data
                bm = bmesh.from_edit_mesh(me)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()

                # Select vertices near the bottom edge
                bpy.ops.mesh.select_all(action='DESELECT')
                z_threshold = edge_z + 2.0  # 2mm tolerance
                for v in bm.verts:
                    world_co = work.matrix_world @ v.co
                    if world_co.z <= z_threshold:
                        v.select = True

                bmesh.update_edit_mesh(me)

                bpy.ops.mesh.select_mode(type='EDGE')
                bpy.ops.mesh.loop_multi_select(ring=False)

                # Extrude downward to create the rim band
                bpy.ops.mesh.extrude_region_move(
                    TRANSFORM_OT_translate={
                        "value": (0, 0, -rim_height_mm),
                        "orient_type": 'GLOBAL',
                    }
                )

                bpy.ops.object.mode_set(mode='OBJECT')

        # --- Recalculate normals ---
        with bpy.context.temp_override(
            object=work, active_object=work, selected_objects=[work]
        ):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        self.report(
            {'INFO'},
            f"Generated: {work.name} "
            f"(clearance={clearance_mm}mm, thickness={thickness_mm}mm, "
            f"rim={rim_height_mm}mm, edge_z={edge_z:.1f}mm)",
        )
        return {'FINISHED'}
