import math

import bpy
import bmesh
from mathutils import Vector


def _edge_z_at_angle(angle, height, forehead_height_mm, edge_ratio):
    """Compute the Z height of the helmet edge at a given angle.

    angle: 0 = right ear, pi/2 = front, pi = left ear, 3pi/2 = back.

    The helmet edge is defined by how far DOWN from the crown each zone
    extends. Think of it as "the helmet covers the top X% of the head":

    - edge_ratio controls overall coverage (0.25 = helmet covers top 75%
      of the head height... but in practice we want to cut more)
    - Front (forehead): the hairline — uses forehead_height to set how
      far down the front of the helmet extends
    - Sides (ears): extends down to just above ear-top level
    - Back (nape): extends lower than sides to cover occipital area

    Returns Z in mm from origin (ear-top level = Z=0).
    """
    # Front edge: sits at forehead_height below crown.
    # forehead_height is hairline-to-brow, so the helmet edge at the
    # front is at crown_z - forehead_height (roughly at the hairline).
    front_z = height - forehead_height_mm

    # Side edge: slightly below ear-top level (Z=0).
    # The helmet wraps just under the ears.
    side_z = -height * 0.10

    # Back edge: extends well below ear level to cover the occipital
    # bump and nape. This is the lowest point of the helmet.
    back_z = -height * 0.20

    sin_a = math.sin(angle)
    cos_a = math.cos(angle)

    front_w = max(0.0, sin_a) ** 2
    back_w = max(0.0, -sin_a) ** 2
    side_w = cos_a ** 2

    total_w = front_w + back_w + side_w
    if total_w > 0:
        return (front_z * front_w + back_z * back_w + side_z * side_w) / total_w
    return height * 0.08


class HWG_OT_GenerateBase(bpy.types.Operator):
    """Generate helmet wig base from tape measurements."""
    bl_idname = "hwg.generate_base"
    bl_label = "Generate Helmet Base"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hwg

        # --- Generate parametric head mesh from measurements (cm -> mm) ---
        from ..core.head_model import generate_head_mesh

        head_height_mm = props.head_height_cm * 10.0
        forehead_height_mm = props.forehead_height_cm * 10.0

        bm = generate_head_mesh(
            head_circumference_mm=props.head_circumference_cm * 10.0,
            front_to_back_arc_mm=props.front_to_back_arc_cm * 10.0,
            ear_to_ear_over_mm=props.ear_to_ear_over_cm * 10.0,
            ear_to_ear_back_mm=props.ear_to_ear_back_cm * 10.0,
            head_width_mm=props.head_width_cm * 10.0,
            head_depth_mm=props.head_depth_cm * 10.0,
            head_height_mm=head_height_mm,
            forehead_width_mm=props.forehead_width_cm * 10.0,
            nape_width_mm=props.nape_width_cm * 10.0,
            forehead_height_mm=forehead_height_mm,
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

        # --- Contoured edge cut ---
        # 1) Delete all vertices clearly below the contour threshold.
        # 2) Move the new boundary vertices (lowest surviving ring per
        #    column) down to the exact contour Z so the edge is smooth.
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
            bpy.ops.object.mode_set(mode='EDIT')
            me = work.data
            bm_edit = bmesh.from_edit_mesh(me)
            bm_edit.verts.ensure_lookup_table()

            # Delete vertices below threshold
            verts_to_delete = []
            for v in bm_edit.verts:
                angle = math.atan2(v.co.y, v.co.x)
                if angle < 0:
                    angle += 2.0 * math.pi
                threshold_z = _edge_z_at_angle(
                    angle, head_height_mm, forehead_height_mm, props.edge_ratio
                )
                if v.co.z < threshold_z:
                    verts_to_delete.append(v)

            if verts_to_delete:
                bmesh.ops.delete(bm_edit, geom=verts_to_delete, context='VERTS')

            # Now find boundary verts (on open edges) and snap them to
            # the exact contour Z. This smooths out the stair-step.
            bm_edit.verts.ensure_lookup_table()
            bm_edit.edges.ensure_lookup_table()
            for v in bm_edit.verts:
                if v.is_boundary:
                    angle = math.atan2(v.co.y, v.co.x)
                    if angle < 0:
                        angle += 2.0 * math.pi
                    target_z = _edge_z_at_angle(
                        angle, head_height_mm, forehead_height_mm,
                        props.edge_ratio,
                    )
                    v.co.z = target_z

            bmesh.update_edit_mesh(me)
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Clearance offset (move vertices outward along normals) ---
        clearance_mm = props.clearance_mm
        if clearance_mm > 0:
            with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
                bpy.ops.object.mode_set(mode='EDIT')
                me = work.data
                bm_clear = bmesh.from_edit_mesh(me)
                bm_clear.verts.ensure_lookup_table()

                bmesh.ops.recalc_face_normals(bm_clear, faces=bm_clear.faces[:])

                for v in bm_clear.verts:
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
                bm_rim = bmesh.from_edit_mesh(me)
                bm_rim.verts.ensure_lookup_table()
                bm_rim.edges.ensure_lookup_table()

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
