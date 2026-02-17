import math

import bpy
import bmesh
from mathutils import Vector


def _edge_z_at_angle(angle, height, forehead_height_mm, edge_ratio):
    """Compute the Z height of the helmet edge at a given angle.

    angle: 0 = right ear, pi/2 = front, pi = left ear, 3pi/2 = back.

    Returns Z in mm. The contour is:
    - Front (forehead): highest — sits above the brow
    - Sides (ears): lowest — just above ears
    - Back (nape): medium-low — covers occipital area
    """
    base_z = height * edge_ratio

    front_z = base_z + forehead_height_mm * 0.3
    side_z = base_z - height * 0.05
    back_z = base_z - height * 0.08

    sin_a = math.sin(angle)
    cos_a = math.cos(angle)

    front_w = max(0.0, sin_a) ** 2
    back_w = max(0.0, -sin_a) ** 2
    side_w = cos_a ** 2

    total_w = front_w + back_w + side_w
    if total_w > 0:
        return (front_z * front_w + back_z * back_w + side_z * side_w) / total_w
    return base_z


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
        # Delete vertices below a per-angle Z threshold, then snap the
        # resulting boundary vertices to the exact contour line for a
        # smooth edge instead of a jagged stair-step.
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
            bpy.ops.object.mode_set(mode='EDIT')
            me = work.data
            bm_edit = bmesh.from_edit_mesh(me)
            bm_edit.verts.ensure_lookup_table()

            # Tag each vertex as above or below its threshold
            above = set()
            below = set()
            for v in bm_edit.verts:
                angle = math.atan2(v.co.y, v.co.x)
                if angle < 0:
                    angle += 2.0 * math.pi
                threshold_z = _edge_z_at_angle(
                    angle, head_height_mm, forehead_height_mm, props.edge_ratio
                )
                if v.co.z < threshold_z:
                    below.add(v)
                else:
                    above.add(v)

            # For edges that cross the threshold (one vert above, one below),
            # split them at the exact crossing point. This creates new verts
            # right on the contour line.
            edges_to_split = []
            for e in bm_edit.edges:
                v0, v1 = e.verts
                if (v0 in above) != (v1 in above):
                    # Edge crosses the threshold — find the split fraction
                    a0 = math.atan2(v0.co.y, v0.co.x)
                    if a0 < 0:
                        a0 += 2.0 * math.pi
                    a1 = math.atan2(v1.co.y, v1.co.x)
                    if a1 < 0:
                        a1 += 2.0 * math.pi

                    # Use average angle for threshold (vertices are close)
                    avg_angle = (a0 + a1) / 2.0
                    threshold_z = _edge_z_at_angle(
                        avg_angle, head_height_mm, forehead_height_mm,
                        props.edge_ratio,
                    )

                    # Linear interpolation: find t where z = threshold_z
                    dz = v1.co.z - v0.co.z
                    if abs(dz) > 0.001:
                        frac = (threshold_z - v0.co.z) / dz
                        frac = max(0.01, min(0.99, frac))
                    else:
                        frac = 0.5

                    edges_to_split.append((e, frac))

            # Split all crossing edges
            for edge, frac in edges_to_split:
                try:
                    new_vert, new_edges = bmesh.utils.edge_split(edge, edge.verts[0], frac)
                    above.add(new_vert)  # New vert is on the threshold — keep it
                except Exception:
                    pass

            # Now delete all original "below" vertices
            bm_edit.verts.ensure_lookup_table()
            verts_to_delete = [v for v in bm_edit.verts if v in below and v.is_valid]
            if verts_to_delete:
                bmesh.ops.delete(bm_edit, geom=verts_to_delete, context='VERTS')

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
