"""Modal operator for drawing a hairline on a head scan mesh.

The user clicks and drags on the scan surface to draw the hairline path.
On confirm (Enter), the raw points are smoothed via Catmull-Rom spline,
resampled to even spacing, re-projected onto the mesh, and stored as
JSON on the scene properties for use by the generate operator.
"""

import bpy
import gpu
import json
import math
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree


class HWG_OT_DrawHairline(bpy.types.Operator):
    """Draw the hairline on the scan mesh surface."""

    bl_idname = "hwg.draw_hairline"
    bl_label = "Draw Hairline"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        props = context.scene.hwg
        self.target_obj = props.scan_object

        if not self.target_obj or self.target_obj.type != 'MESH':
            self.report({'ERROR'}, "Set a scan object first.")
            return {'CANCELLED'}

        # Build BVH tree for raycasting
        depsgraph = context.evaluated_depsgraph_get()
        self.bvh = BVHTree.FromObject(self.target_obj, depsgraph)
        self.matrix_world = self.target_obj.matrix_world.copy()
        self.matrix_world_inv = self.matrix_world.inverted()

        self.points = []  # raw 3D points on mesh surface (world space)
        self.is_drawing = False
        self.batch = None
        self.shader = None

        # Register viewport draw callback
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (context,), 'WINDOW', 'POST_VIEW'
        )
        context.window_manager.modal_handler_add(self)

        # Show header instructions
        context.area.header_text_set(
            "Draw Hairline: LMB drag to draw | Enter to confirm | Esc to cancel"
        )
        return {'RUNNING_MODAL'}

    # Events to pass through for viewport navigation (orbit, pan, zoom)
    _nav_events = {
        'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
        'NUMPAD_0', 'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3',
        'NUMPAD_4', 'NUMPAD_5', 'NUMPAD_6', 'NUMPAD_7',
        'NUMPAD_8', 'NUMPAD_9', 'NUMPAD_PERIOD',
    }

    def modal(self, context, event):
        context.area.tag_redraw()

        # Let viewport navigation pass through (orbit, pan, zoom)
        if event.type in self._nav_events:
            return {'PASS_THROUGH'}

        # Shift/Ctrl + MMB (pan/zoom) also needs passthrough on modifier keys
        if event.type == 'MOUSEMOVE' and not self.is_drawing:
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE' and self.is_drawing:
            hit = self._raycast_mouse(context, event)
            if hit is not None:
                # Only add if far enough from last point (avoid clustering)
                if not self.points or (hit - self.points[-1]).length > 1.0:
                    self.points.append(hit)
                    self._rebuild_batch()

        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.is_drawing = True
                hit = self._raycast_mouse(context, event)
                if hit is not None:
                    self.points.append(hit)
                    self._rebuild_batch()
            elif event.value == 'RELEASE':
                self.is_drawing = False

        elif event.type in {'RET', 'NUMPAD_ENTER'}:
            self._finish(context)
            return {'FINISHED'}

        elif event.type == 'ESC':
            self._cancel(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    # ------------------------------------------------------------------
    # Raycasting
    # ------------------------------------------------------------------

    def _raycast_mouse(self, context, event):
        """Cast a ray from the mouse onto the scan mesh, return world-space hit point."""
        region = context.region
        rv3d = context.region_data
        coord = (event.mouse_region_x, event.mouse_region_y)

        ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

        # Transform ray into object local space
        ray_origin_local = self.matrix_world_inv @ ray_origin
        ray_dir_local = (self.matrix_world_inv.to_3x3() @ ray_direction).normalized()

        location, normal, face_index, distance = self.bvh.ray_cast(
            ray_origin_local, ray_dir_local
        )
        if location is not None:
            return self.matrix_world @ location
        return None

    # ------------------------------------------------------------------
    # Viewport drawing
    # ------------------------------------------------------------------

    def _rebuild_batch(self):
        """Rebuild the GPU batch for the current point list."""
        if len(self.points) < 2:
            self.batch = None
            return
        coords = [(p.x, p.y, p.z) for p in self.points]
        self.shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        self.batch = batch_for_shader(
            self.shader, 'LINE_STRIP', {"pos": coords}
        )

    def _draw_callback(self, context):
        """Draw the hairline polyline in the viewport."""
        if self.batch is None or self.shader is None:
            return
        self.shader.bind()
        region = context.region
        self.shader.uniform_float("viewportSize", (region.width, region.height))
        self.shader.uniform_float("lineWidth", 3.0)
        self.shader.uniform_float("color", (1.0, 0.4, 0.0, 1.0))  # Orange
        self.batch.draw(self.shader)

    # ------------------------------------------------------------------
    # Smoothing
    # ------------------------------------------------------------------

    def _smooth_points(self, pts, resample_dist=2.0):
        """Smooth raw points using Catmull-Rom spline, resample evenly.

        Args:
            pts: list of Vector (world space)
            resample_dist: target distance between resampled points (mm)

        Returns:
            list of Vector (smoothed, evenly spaced)
        """
        if len(pts) < 4:
            return pts[:]

        # Catmull-Rom interpolation
        def catmull_rom(p0, p1, p2, p3, t):
            t2 = t * t
            t3 = t2 * t
            return 0.5 * (
                (2.0 * p1) +
                (-p0 + p2) * t +
                (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2 +
                (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
            )

        # Generate dense spline points
        dense = []
        n = len(pts)
        steps_per_segment = 10
        for i in range(n - 1):
            p0 = pts[max(i - 1, 0)]
            p1 = pts[i]
            p2 = pts[min(i + 1, n - 1)]
            p3 = pts[min(i + 2, n - 1)]
            for s in range(steps_per_segment):
                t = s / steps_per_segment
                dense.append(catmull_rom(p0, p1, p2, p3, t))
        dense.append(pts[-1])

        # Resample to even spacing
        if len(dense) < 2:
            return dense

        resampled = [dense[0]]
        accum = 0.0
        for i in range(1, len(dense)):
            seg_len = (dense[i] - dense[i - 1]).length
            accum += seg_len
            if accum >= resample_dist:
                resampled.append(dense[i].copy())
                accum = 0.0
        # Always include last point
        if (resampled[-1] - dense[-1]).length > 0.1:
            resampled.append(dense[-1])

        return resampled

    def _reproject_to_surface(self, points):
        """Re-project smoothed points back onto the mesh surface."""
        reprojected = []
        for pt in points:
            local_pt = self.matrix_world_inv @ pt
            result, location, normal, face_index = self.target_obj.closest_point_on_mesh(
                local_pt
            )
            if result:
                reprojected.append(self.matrix_world @ location)
            else:
                reprojected.append(pt)
        return reprojected

    # ------------------------------------------------------------------
    # Confirm / Cancel
    # ------------------------------------------------------------------

    def _finish(self, context):
        """Smooth the drawn points, store them, and clean up."""
        bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
        context.area.header_text_set(None)

        if len(self.points) < 3:
            self.report({'WARNING'}, "Not enough points drawn. Draw a longer line.")
            return

        # Smooth and resample
        smoothed = self._smooth_points(self.points)

        # Re-project onto mesh surface
        smoothed = self._reproject_to_surface(smoothed)

        # Store as JSON on scene property
        pts_list = [[p.x, p.y, p.z] for p in smoothed]
        context.scene.hwg.hairline_points_json = json.dumps(pts_list)

        self.report({'INFO'}, f"Hairline set: {len(smoothed)} points")
        context.area.tag_redraw()

    def _cancel(self, context):
        """Discard drawn points and clean up."""
        bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
        context.area.header_text_set(None)
        self.points = []
        self.report({'INFO'}, "Hairline drawing cancelled.")
        context.area.tag_redraw()
