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
        # The head model now builds the contoured edge line directly into
        # the mesh — no flat bisect cut needed. The edge_ratio controls
        # how much of the lower head is included.
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
            edge_ratio=props.edge_ratio,
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

        # --- Delete the bottom cap face to create an open shell ---
        # The head model includes a bottom cap for manifold-ness,
        # but we need the bottom open for solidify to work correctly.
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
            bpy.ops.object.mode_set(mode='EDIT')
            me = work.data
            bm_edit = bmesh.from_edit_mesh(me)
            bm_edit.faces.ensure_lookup_table()

            # Find and delete the bottom cap face (the n-gon at the bottom).
            # It's the face with the most vertices (u_segments sides).
            cap_face = max(bm_edit.faces, key=lambda f: len(f.verts))
            bmesh.ops.delete(bm_edit, geom=[cap_face], context='FACES')

            bmesh.update_edit_mesh(me)
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Clearance offset (move vertices outward along normals) ---
        # This pushes the single-wall surface outward so the helmet sits
        # above the head rather than directly on it.
        clearance_mm = props.clearance_mm
        if clearance_mm > 0:
            with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
                bpy.ops.object.mode_set(mode='EDIT')
                me = work.data
                bm_clear = bmesh.from_edit_mesh(me)
                bm_clear.verts.ensure_lookup_table()

                # Recalculate normals so they point outward
                bmesh.ops.recalc_face_normals(bm_clear, faces=bm_clear.faces[:])

                for v in bm_clear.verts:
                    # Average face normal of adjacent faces
                    if v.link_faces:
                        avg_normal = Vector((0, 0, 0))
                        for f in v.link_faces:
                            avg_normal += f.normal
                        avg_normal.normalize()
                        v.co += avg_normal * clearance_mm
                    else:
                        v.co += v.normal * clearance_mm

                bmesh.update_edit_mesh(me)
                bpy.ops.object.mode_set(mode='OBJECT')

        # --- Shell thickness (Solidify into a hollow shell) ---
        # The mesh is currently a single-wall open surface (dome with open bottom).
        # Solidify creates inner+outer walls with thickness, and use_rim connects
        # them at the open bottom edge to form a proper shell.
        thickness_mm = props.thickness_mm
        mod_shell = work.modifiers.new("HWG_Shell", 'SOLIDIFY')
        mod_shell.thickness = thickness_mm
        mod_shell.offset = -1.0          # Thicken inward from outer surface
        mod_shell.use_rim = True          # Close the open bottom edge
        mod_shell.use_rim_only = False
        mod_shell.use_even_offset = True
        with bpy.context.temp_override(object=work, active_object=work):
            bpy.ops.object.modifier_apply(modifier=mod_shell.name)

        # --- Rim band reinforcement ---
        # Extrude the bottom edge loop downward to create a thicker rim
        rim_height_mm = props.rim_height_mm
        if rim_height_mm > 0:
            with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
                bpy.ops.object.mode_set(mode='EDIT')

                me = work.data
                bm_rim = bmesh.from_edit_mesh(me)
                bm_rim.verts.ensure_lookup_table()
                bm_rim.edges.ensure_lookup_table()

                # Select only the boundary (open) edges at the bottom rim
                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.mesh.select_non_manifold(
                    extend=False, use_wire=False,
                    use_boundary=True, use_multi_face=False,
                    use_non_contiguous=False, use_verts=False,
                )

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
            f"rim={rim_height_mm}mm, edge_ratio={props.edge_ratio:.0%})"
        )
        return {'FINISHED'}
