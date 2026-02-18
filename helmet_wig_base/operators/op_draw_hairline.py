"""Modal operator for drawing a hairline on a head scan mesh.

The user clicks and drags on the scan surface to draw the hairline path.
On confirm (Enter), the raw points are smoothed via Catmull-Rom spline,
resampled to even spacing, re-projected onto the mesh, and stored as
JSON on the scene properties for use by the generate operator.

A persistent viewport overlay shows the stored hairline (green) so the
user can always see where the final cut line is. During drawing, raw
points are shown in orange and a live smoothed preview in cyan.
"""

import bpy
import json
import math
from mathutils import Vector
from mathutils.bvhtree import BVHTree

# GPU and viewport modules are unavailable in headless (--background) mode.
# Guard imports so the module can still be loaded headless for the JSON
# hairline data and smoothing functions.
if not bpy.app.background:
    import gpu
    from gpu_extras.batch import batch_for_shader
    from bpy_extras import view3d_utils


# ------------------------------------------------------------------
# Persistent hairline overlay (always visible when data exists)
# ------------------------------------------------------------------

_persistent_draw_handle = None
_persistent_batch = None
_persistent_shader = None


def _persistent_draw_callback():
    """Draw the stored hairline as a green line in the viewport."""
    global _persistent_batch, _persistent_shader
    if _persistent_batch is None or _persistent_shader is None:
        return

    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set('ALPHA')

    _persistent_shader.bind()
    region = bpy.context.region
    if region:
        _persistent_shader.uniform_float("viewportSize", (region.width, region.height))
    _persistent_shader.uniform_float("lineWidth", 4.0)
    _persistent_shader.uniform_float("color", (0.0, 1.0, 0.3, 0.9))  # Green
    _persistent_batch.draw(_persistent_shader)

    gpu.state.blend_set('NONE')
    gpu.state.depth_test_set('NONE')
    gpu.state.depth_mask_set(True)


def refresh_persistent_overlay(context=None):
    """Rebuild the persistent overlay batch from stored hairline JSON.

    Call this after hairline data changes (confirm, clear, load).
    """
    global _persistent_batch, _persistent_shader

    scene = context.scene if context else bpy.context.scene
    props = scene.hwg
    hairline_json = props.hairline_points_json

    if not hairline_json:
        _persistent_batch = None
        _persistent_shader = None
        return

    try:
        pts = json.loads(hairline_json)
    except (json.JSONDecodeError, TypeError):
        _persistent_batch = None
        _persistent_shader = None
        return

    if len(pts) < 2:
        _persistent_batch = None
        _persistent_shader = None
        return

    coords = [(p[0], p[1], p[2]) for p in pts]
    _persistent_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    _persistent_batch = batch_for_shader(
        _persistent_shader, 'LINE_STRIP', {"pos": coords}
    )


def register_persistent_overlay():
    """Register the persistent draw handler (called once at addon registration)."""
    global _persistent_draw_handle
    if _persistent_draw_handle is None:
        _persistent_draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            _persistent_draw_callback, (), 'WINDOW', 'POST_VIEW'
        )


def unregister_persistent_overlay():
    """Unregister the persistent draw handler (called at addon unregistration)."""
    global _persistent_draw_handle, _persistent_batch, _persistent_shader
    if _persistent_draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_persistent_draw_handle, 'WINDOW')
        _persistent_draw_handle = None
    _persistent_batch = None
    _persistent_shader = None


# ------------------------------------------------------------------
# Modal drawing operator
# ------------------------------------------------------------------

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
        self.is_erasing = False
        self.erase_radius = 5.0  # world-space radius for eraser (mm)

        # Raw line batch (orange)
        self.batch_raw = None
        self.shader_raw = None

        # Live smoothed preview batch (cyan)
        self.batch_smooth = None
        self.shader_smooth = None

        # Register viewport draw callback for this modal session
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (context,), 'WINDOW', 'POST_VIEW'
        )
        context.window_manager.modal_handler_add(self)

        # Show header instructions
        context.area.header_text_set(
            "Draw Hairline: LMB draw | Ctrl+LMB erase | Enter confirm | Esc cancel"
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

        # Pass through mouse movement when not drawing or erasing
        if event.type == 'MOUSEMOVE' and not self.is_drawing and not self.is_erasing:
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE' and self.is_erasing:
            self._erase_at_mouse(context, event)

        elif event.type == 'MOUSEMOVE' and self.is_drawing:
            hit = self._raycast_mouse(context, event)
            if hit is not None:
                # Only add if far enough from last point (avoid clustering)
                if not self.points or (hit - self.points[-1]).length > 1.0:
                    self.points.append(hit)
                    self._rebuild_raw_batch()

        elif event.type == 'LEFTMOUSE':
            if event.value == 'PRESS' and event.ctrl:
                # Ctrl+LMB = erase mode
                self.is_erasing = True
                self._erase_at_mouse(context, event)
            elif event.value == 'PRESS':
                # LMB = draw mode
                self.is_drawing = True
                hit = self._raycast_mouse(context, event)
                if hit is not None:
                    self.points.append(hit)
                    self._rebuild_raw_batch()
            elif event.value == 'RELEASE':
                was_drawing = self.is_drawing
                was_erasing = self.is_erasing
                self.is_drawing = False
                self.is_erasing = False
                # Update the smoothed preview on stroke end
                if (was_drawing or was_erasing) and len(self.points) >= 4:
                    self._rebuild_smooth_batch()

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
    # Erasing
    # ------------------------------------------------------------------

    def _erase_at_mouse(self, context, event):
        """Remove points near the mouse cursor on the mesh surface."""
        hit = self._raycast_mouse(context, event)
        if hit is None or not self.points:
            return

        before = len(self.points)
        self.points = [
            p for p in self.points
            if (p - hit).length > self.erase_radius
        ]
        if len(self.points) != before:
            self._rebuild_raw_batch()

    # ------------------------------------------------------------------
    # Viewport drawing
    # ------------------------------------------------------------------

    def _rebuild_raw_batch(self):
        """Rebuild the GPU batch for the raw drawn points (orange)."""
        if len(self.points) < 2:
            self.batch_raw = None
            return
        coords = [(p.x, p.y, p.z) for p in self.points]
        self.shader_raw = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        self.batch_raw = batch_for_shader(
            self.shader_raw, 'LINE_STRIP', {"pos": coords}
        )

    def _rebuild_smooth_batch(self):
        """Rebuild the GPU batch for the live smoothed preview (cyan)."""
        if len(self.points) < 4:
            self.batch_smooth = None
            return

        # Run the same smoothing pipeline as _finish
        smoothed = self._smooth_points(self.points, resample_dist=2.0)
        smoothed = self._reproject_to_surface(smoothed)

        if len(smoothed) < 2:
            self.batch_smooth = None
            return

        coords = [(p.x, p.y, p.z) for p in smoothed]
        self.shader_smooth = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        self.batch_smooth = batch_for_shader(
            self.shader_smooth, 'LINE_STRIP', {"pos": coords}
        )

    def _draw_callback(self, context):
        """Draw the raw line (orange) and smoothed preview (cyan) in the viewport."""
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(False)

        region = context.region

        # Draw smoothed preview first (underneath) — cyan
        if self.batch_smooth is not None and self.shader_smooth is not None:
            self.shader_smooth.bind()
            self.shader_smooth.uniform_float("viewportSize", (region.width, region.height))
            self.shader_smooth.uniform_float("lineWidth", 5.0)
            self.shader_smooth.uniform_float("color", (0.0, 0.9, 1.0, 0.8))  # Cyan
            self.batch_smooth.draw(self.shader_smooth)

        # Draw raw points on top — orange
        if self.batch_raw is not None and self.shader_raw is not None:
            self.shader_raw.bind()
            self.shader_raw.uniform_float("viewportSize", (region.width, region.height))
            self.shader_raw.uniform_float("lineWidth", 2.0)
            self.shader_raw.uniform_float("color", (1.0, 0.4, 0.0, 1.0))  # Orange
            self.batch_raw.draw(self.shader_raw)

        # Restore default state
        gpu.state.depth_test_set('NONE')
        gpu.state.depth_mask_set(True)

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
        """Smooth the drawn points, store them, and clean up.

        Pipeline:
        1. Catmull-Rom spline + even resampling (2mm)
        2. Re-project onto mesh surface
        3. Store as JSON on scene property
        4. Auto-save to tests/fixtures/ for automated testing
        5. Update persistent overlay
        """
        bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
        context.area.header_text_set(None)

        if len(self.points) < 3:
            self.report({'WARNING'}, "Not enough points drawn. Draw a longer line.")
            return

        # Pass 1: Catmull-Rom spline + even resampling
        smoothed = self._smooth_points(self.points, resample_dist=2.0)

        # Pass 2: Re-project onto mesh surface
        smoothed = self._reproject_to_surface(smoothed)

        # Store as JSON on scene property
        pts_list = [[p.x, p.y, p.z] for p in smoothed]
        hairline_json = json.dumps(pts_list)
        context.scene.hwg.hairline_points_json = hairline_json

        # Auto-save to tests/fixtures/ for headless testing.
        # File: tests/fixtures/hairline_<scan_name>_<N>.json
        # N auto-increments so each draw creates a new fixture.
        self._auto_save_fixture(context, hairline_json)

        # Update the persistent green overlay to show the final line
        refresh_persistent_overlay(context)

        self.report({'INFO'}, f"Hairline set: {len(smoothed)} points")
        context.area.tag_redraw()

    def _auto_save_fixture(self, context, hairline_json):
        """Save hairline JSON to tests/fixtures/ for automated testing."""
        import os

        # Find the repo root (parent of helmet_wig_base/)
        addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        repo_root = os.path.dirname(addon_dir)
        fixtures_dir = os.path.join(repo_root, "tests", "fixtures")

        # Create fixtures dir if needed
        os.makedirs(fixtures_dir, exist_ok=True)

        # Get scan object name for the filename
        scan_name = "unknown"
        props = context.scene.hwg
        if props.scan_object:
            # Clean the name for use in a filename
            scan_name = props.scan_object.name
            scan_name = scan_name.replace(" ", "_").replace(".", "_")

        # Find next available number
        n = 1
        while True:
            filename = f"hairline_{scan_name}_{n}.json"
            filepath = os.path.join(fixtures_dir, filename)
            if not os.path.exists(filepath):
                break
            n += 1

        # Save
        try:
            with open(filepath, "w") as f:
                f.write(hairline_json)
            self.report(
                {'INFO'},
                f"Hairline saved: {filename}",
            )
        except (IOError, OSError) as e:
            self.report(
                {'WARNING'},
                f"Could not auto-save hairline fixture: {e}",
            )

    def _cancel(self, context):
        """Discard drawn points and clean up."""
        bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
        context.area.header_text_set(None)
        self.points = []
        self.report({'INFO'}, "Hairline drawing cancelled.")
        context.area.tag_redraw()
