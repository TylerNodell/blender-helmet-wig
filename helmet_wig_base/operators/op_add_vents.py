import bpy
import bmesh
from mathutils import Vector
import math


class HWG_OT_AddVents(bpy.types.Operator):
    """Add ventilation holes to the helmet base mesh."""
    bl_idname = "hwg.add_vents"
    bl_label = "Add Vents"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.hwg
        
        if not props.vents_enabled:
            self.report({'WARNING'}, "Vents are disabled in settings.")
            return {'CANCELLED'}
        
        # Get active object (helmet base)
        helmet = context.active_object
        if not helmet or helmet.type != 'MESH':
            self.report({'ERROR'}, "Select a helmet base mesh object first.")
            return {'CANCELLED'}
        
        # Get vent parameters
        vent_radius = props.vent_radius_mm
        vent_spacing = props.vent_spacing_mm
        vent_margin = props.vent_margin_mm
        
        # Calculate the bounding box to determine the dome area and bottom edge
        bbox = [helmet.matrix_world @ Vector(corner) for corner in helmet.bound_box]
        z_vals = [v.z for v in bbox]
        z_min, z_max = min(z_vals), max(z_vals)
        
        # Vents should not be placed within vent_margin_mm from the bottom edge
        vent_zone_min_z = z_min + vent_margin
        
        # Create vent positions in a grid pattern
        vent_positions = self._generate_vent_grid(
            helmet, 
            vent_spacing, 
            vent_zone_min_z, 
            z_max
        )
        
        if not vent_positions:
            self.report({'WARNING'}, "No valid vent positions found. Try adjusting spacing or margin.")
            return {'CANCELLED'}
        
        # Create a single collection of cylinder cutters
        cutter_name = f"{helmet.name}_VENT_CUTTERS"
        cutter_collection = self._create_vent_cutters(
            vent_positions, 
            vent_radius, 
            cutter_name
        )
        
        if not cutter_collection:
            self.report({'ERROR'}, "Failed to create vent cutters.")
            return {'CANCELLED'}
        
        # Apply boolean difference modifier using the cutter collection
        mod_bool = helmet.modifiers.new(name="HWG_Vents", type='BOOLEAN')
        mod_bool.operation = 'DIFFERENCE'
        mod_bool.object = cutter_collection
        mod_bool.solver = 'EXACT'
        mod_bool.use_self = True
        
        # Apply the modifier
        with bpy.context.temp_override(object=helmet, active_object=helmet):
            try:
                bpy.ops.object.modifier_apply(modifier=mod_bool.name)
            except Exception as e:
                self.report({'ERROR'}, f"Boolean operation failed: {e}")
                return {'CANCELLED'}
        
        # Clean up the cutter object
        bpy.data.objects.remove(cutter_collection, do_unlink=True)
        
        self.report(
            {'INFO'}, 
            f"Added {len(vent_positions)} vents (radius={vent_radius}mm, spacing={vent_spacing}mm)"
        )
        return {'FINISHED'}
    
    def _generate_vent_grid(self, helmet, spacing, z_min, z_max):
        """Generate a grid of vent positions projected onto the helmet surface."""
        positions = []
        
        # Get helmet bounding box in world space
        bbox = [helmet.matrix_world @ Vector(corner) for corner in helmet.bound_box]
        x_vals = [v.x for v in bbox]
        y_vals = [v.y for v in bbox]
        
        x_min, x_max = min(x_vals), max(x_vals)
        y_min, y_max = min(y_vals), max(y_vals)
        
        # Create a BVH tree for raycasting
        import mathutils
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = helmet.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        
        # Build BVH tree
        bvh = mathutils.bvhtree.BVHTree.FromPolygons(
            [v.co for v in mesh.vertices],
            [p.vertices for p in mesh.polygons]
        )
        
        # Generate grid positions
        x = x_min
        row = 0
        while x <= x_max:
            y = y_min
            # Offset every other row for better distribution
            if row % 2 == 1:
                y += spacing * 0.5
            
            while y <= y_max:
                # Cast ray downward from above the helmet
                ray_origin = Vector((x, y, z_max + 10.0))
                ray_direction = Vector((0, 0, -1))
                
                location, normal, index, distance = bvh.ray_cast(ray_origin, ray_direction)
                
                if location:
                    # Check if the hit point is within the valid z range
                    if location.z >= z_min and location.z <= z_max:
                        # Apply margin check
                        if location.z >= z_min:
                            positions.append((location.copy(), normal.copy()))
                
                y += spacing
            x += spacing
            row += 1
        
        eval_obj.to_mesh_clear()
        return positions
    
    def _create_vent_cutters(self, positions, radius, name):
        """Create a joined mesh of all vent cylinder cutters."""
        bpy.ops.object.select_all(action='DESELECT')
        
        cylinders = []
        
        for location, normal in positions:
            # Create a cylinder at each position
            # The cylinder should be oriented along the surface normal
            # and be long enough to penetrate the shell
            depth = 20.0  # Make it long enough to go through the shell
            
            bpy.ops.mesh.primitive_cylinder_add(
                radius=radius,
                depth=depth,
                location=location,
                rotation=(0, 0, 0)
            )
            
            cyl = bpy.context.active_object
            cylinders.append(cyl)
            
            # Orient cylinder along the normal (pointing inward)
            # The normal points outward, so we want to point inward (negative normal)
            up = Vector((0, 0, 1))
            rotation = up.rotation_difference(-normal)
            cyl.rotation_euler = rotation.to_euler()
            
            cyl.select_set(True)
        
        if not cylinders:
            return None
        
        # Join all cylinders into one object
        bpy.context.view_layer.objects.active = cylinders[0]
        with bpy.context.temp_override(active_object=cylinders[0], selected_objects=cylinders):
            bpy.ops.object.join()
        
        cutter = bpy.context.active_object
        cutter.name = name
        cutter.display_type = 'WIRE'
        
        return cutter


classes = (HWG_OT_AddVents,)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
