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

        # --- Apply scale from meta.json ---
        # Convert meters → mm if scan is in meters
        unit_scale = 1000.0 if props.scan_units == 'M' else 1.0
        total_scale = unit_scale * props.scale_factor

        if abs(total_scale - 1.0) > 0.0001:
            work.scale = (total_scale, total_scale, total_scale)
            # Apply scale transform
            with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        # --- Center on geometry bounds ---
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        work.location = (0.0, 0.0, 0.0)

        # --- Compute bounding box for edge cut ---
        # After transforms, read bbox from mesh data
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
                use_fill=True,  # fill the cut to create a solid bottom
            )
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Hole filling (prevent solidify artifacts on incomplete scans) ---
        with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
            bpy.ops.object.mode_set(mode='EDIT')
            
            # Use bmesh to fill boundary holes
            me = work.data
            bm = bmesh.from_edit_mesh(me)
            
            # Select all non-manifold edges (boundary edges)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_non_manifold(extend=False, use_wire=False, 
                                              use_boundary=True, use_multi_face=False,
                                              use_non_contiguous=False, use_verts=False)
            
            # Fill holes
            bpy.ops.mesh.edge_face_add()
            bpy.ops.mesh.fill_holes(sides=0)  # 0 = fill all holes regardless of edge count
            
            bmesh.update_edit_mesh(me)
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.mode_set(mode='OBJECT')

        # --- Clearance offset (Solidify outward, then remove inner) ---
        # We use Solidify with offset=1 to push the surface outward by clearance amount.
        # Then apply and delete the inner faces.
        # Simpler approach: use Shrinkwrap + offset, but Solidify is more predictable.
        clearance_mm = props.clearance_mm
        if clearance_mm > 0:
            mod_clear = work.modifiers.new("HWG_Clearance", 'SOLIDIFY')
            mod_clear.thickness = clearance_mm  # already in mm (we converted above)
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

        # --- Rim band reinforcement (structural stiffness) ---
        rim_height_mm = props.rim_height_mm
        if rim_height_mm > 0:
            with bpy.context.temp_override(object=work, active_object=work, selected_objects=[work]):
                bpy.ops.object.mode_set(mode='EDIT')
                
                # Use bmesh to select the bottom edge loop
                me = work.data
                bm = bmesh.from_edit_mesh(me)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                
                # Find the bottom-most edges (near edge_z)
                bpy.ops.mesh.select_all(action='DESELECT')
                
                # Select vertices near the bottom edge
                z_threshold = edge_z + 2.0  # 2mm tolerance
                for v in bm.verts:
                    world_co = work.matrix_world @ v.co
                    if world_co.z <= z_threshold:
                        v.select = True
                
                bmesh.update_edit_mesh(me)
                
                # Select the edge loop from selected vertices
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
