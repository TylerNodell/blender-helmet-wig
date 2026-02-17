import bpy
import bmesh
from mathutils import Vector


class HWG_OT_GenerateBase(bpy.types.Operator):
    """Generate helmet wig base from tape measurements."""
    bl_idname = "hwg.generate_base"
    bl_label = "Generate Helmet Base"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hwg

        # --- Generate parametric head mesh from measurements (cm -> mm) ---
        from ..core.head_model import generate_head_mesh

        bm = generate_head_mesh(
            head_circumference_mm=props.head_circumference_cm * 10.0,
            front_to_back_arc_mm=props.front_to_back_arc_cm * 10.0,
            ear_to_ear_over_mm=props.ear_to_ear_over_cm * 10.0,
            ear_to_ear_back_mm=props.ear_to_ear_back_cm * 10.0,
            head_width_mm=props.head_width_cm * 10.0,
            head_depth_mm=props.head_depth_cm * 10.0,
            head_height_mm=props.head_height_cm * 10.0,
            forehead_width_mm=props.forehead_width_cm * 10.0,
            nape_width_mm=props.nape_width_cm * 10.0,
            forehead_height_mm=props.forehead_height_cm * 10.0,
        )

        # --- Create Blender object from bmesh ---
        mesh_data = bpy.data.meshes.new("HWG_HeadModel")
        bm.to_mesh(mesh_data)
        bm.free()

        work = bpy.data.objects.new("HELMET_BASE", mesh_data)
        context.collection.objects.link(work)

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
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
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

        # --- Hole filling (safety net for non-manifold edges) ---
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
            bpy.ops.object.mode_set(mode='EDIT')

            me = work.data
            bm = bmesh.from_edit_mesh(me)

            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(extend=False, use_wire=False,
                                              use_boundary=True, use_multi_face=False,
                                              use_non_contiguous=False, use_verts=False)

            bpy.ops.mesh.edge_face_add()
            bpy.ops.mesh.fill_holes(sides=0)

            bmesh.update_edit_mesh(me)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Clearance offset (Solidify outward) ---
        clearance_mm = props.clearance_mm
        if clearance_mm > 0:
            mod_clear = work.modifiers.new("HWG_Clearance", 'SOLIDIFY')
            mod_clear.thickness = clearance_mm
            mod_clear.offset = 1.0
            mod_clear.use_rim = False
            mod_clear.use_even_offset = True
            with bpy.context.temp_override(object=work, active_object=work):
                bpy.ops.object.modifier_apply(modifier=mod_clear.name)

        # --- Shell thickness ---
        thickness_mm = props.thickness_mm
        mod_shell = work.modifiers.new("HWG_Shell", 'SOLIDIFY')
        mod_shell.thickness = thickness_mm
        mod_shell.offset = -1.0
        mod_shell.use_rim = True
        mod_shell.use_rim_only = False
        mod_shell.use_even_offset = True
        with bpy.context.temp_override(object=work, active_object=work):
            bpy.ops.object.modifier_apply(modifier=mod_shell.name)

        # --- Rim band reinforcement ---
        rim_height_mm = props.rim_height_mm
        if rim_height_mm > 0:
            with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
                bpy.ops.object.mode_set(mode='EDIT')

                me = work.data
                bm = bmesh.from_edit_mesh(me)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()

                bpy.ops.mesh.select_all(action='DESELECT')

                z_threshold = edge_z + 2.0
                for v in bm.verts:
                    world_co = work.matrix_world @ v.co
                    if world_co.z <= z_threshold:
                        v.select = True

                bmesh.update_edit_mesh(me)

                bpy.ops.mesh.select_mode(type='EDGE')
                bpy.ops.mesh.loop_multi_select(ring=False)

                bpy.ops.mesh.extrude_region_move(
                    TRANSFORM_OT_translate={
                        "value": (0, 0, -rim_height_mm),
                        "orient_type": 'GLOBAL',
                    }
                )

                bpy.ops.object.mode_set(mode='OBJECT')

        # --- Recalculate normals ---
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        self.report(
            {'INFO'},
            f"Generated: {work.name} "
            f"(clearance={clearance_mm}mm, thickness={thickness_mm}mm, "
            f"rim={rim_height_mm}mm, edge_z={edge_z:.1f}mm)"
        )
        return {'FINISHED'}
