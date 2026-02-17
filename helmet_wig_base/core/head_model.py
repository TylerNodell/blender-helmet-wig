"""Parametric head mesh generator from tape measurements.

Generates a head-shaped mesh using profile-based cross-section lofting
with anatomical deformations. All math in millimeters.

Key anatomical features modeled:
- Egg-shaped top-down profile (longer front-to-back than side-to-side)
- Nearly vertical sides in the lower half (above ears), curving over at top
- Forehead is flat/vertical, occiput (back) is rounded and prominent
- Widest point is above ear level at the parietal bones
- Temple indent below the parietal width
- Crown sits slightly behind center
- Occipital bump at lower-back of head
- Forehead and nape are narrower than max width
"""

import math
import bmesh


def _smoothstep(t):
    """Hermite smoothstep for C1-continuous blending."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _half_ellipse_arc(a, b):
    """Approximate half-perimeter of an ellipse (Ramanujan)."""
    if (a + b) <= 0:
        return 0.0
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1.0 + 3.0 * h / (10.0 + math.sqrt(4.0 - 3.0 * h))) / 2.0


def _lerp(a, b, t):
    """Linear interpolation."""
    return a + (b - a) * t


def _width_profile(t):
    """Width falloff from ear level (t=0) to crown (t=1).

    Returns a factor 0..1 where 1 = full width.

    A real head viewed from the front is shaped like a rounded rectangle:
    nearly vertical sides for the bottom ~60%, then a smooth curve over
    the top. The top of the head is still quite broad — NOT a point or
    a narrow circle.

    Key insight: the head maintains ~90%+ of its max width for most of
    its height. The rapid curve-over only happens in the top ~25%.
    """
    if t < 0.05:
        # Temple zone: very slight indent
        return _lerp(0.97, 0.99, _smoothstep(t / 0.05))
    elif t < 0.15:
        # Parietal bulge: reaches full width
        return _lerp(0.99, 1.0, _smoothstep((t - 0.05) / 0.10))
    elif t < 0.60:
        # Long nearly-vertical zone: very slight taper
        frac = (t - 0.15) / 0.45
        return _lerp(1.0, 0.95, frac * frac)
    elif t < 0.85:
        # Dome curve: moderate inward curve
        frac = (t - 0.60) / 0.25
        return _lerp(0.95, 0.55, _smoothstep(frac))
    else:
        # Crown cap: still fairly broad, not a pinch point
        frac = (t - 0.85) / 0.15
        return _lerp(0.55, 0.25, _smoothstep(frac))


def _depth_profile(t):
    """Depth falloff from ear level (t=0) to crown (t=1).

    Same idea as width but stays fuller a bit longer (head is oval,
    longer front-to-back).
    """
    if t < 0.10:
        return _lerp(0.97, 1.0, _smoothstep(t / 0.10))
    elif t < 0.65:
        frac = (t - 0.10) / 0.55
        return _lerp(1.0, 0.93, frac * frac)
    elif t < 0.85:
        frac = (t - 0.65) / 0.20
        return _lerp(0.93, 0.50, _smoothstep(frac))
    else:
        frac = (t - 0.85) / 0.15
        return _lerp(0.50, 0.25, _smoothstep(frac))


def generate_head_mesh(
    head_circumference_mm,
    front_to_back_arc_mm,
    ear_to_ear_over_mm,
    ear_to_ear_back_mm,
    head_width_mm,
    head_depth_mm,
    head_height_mm,
    forehead_width_mm,
    nape_width_mm,
    forehead_height_mm,
    u_segments=64,
    v_segments=48,
):
    """Generate a parametric head mesh from tape measurements.

    Produces a closed mesh from Z=0 (ear-top level) to Z=height (crown).
    The bottom is flat at Z=0 — the contoured helmet edge is applied
    later by the operator.

    Coordinate system: X = left-right, Y = front-back (positive = front),
    Z = up. Origin at center of head at ear-top level.

    Returns:
        bmesh.types.BMesh: Closed, manifold mesh representing the head shape.
    """
    # --- Base dimensions ---
    half_width = head_width_mm / 2.0
    half_depth = head_depth_mm / 2.0
    height = head_height_mm
    forehead_half = forehead_width_mm / 2.0
    nape_half = nape_width_mm / 2.0

    # --- Circumference correction ---
    expected_circ = 2.0 * _half_ellipse_arc(half_width, half_depth)
    if expected_circ > 0:
        circ_scale = head_circumference_mm / expected_circ
        half_width *= circ_scale
        half_depth *= circ_scale
        forehead_half *= circ_scale
        nape_half *= circ_scale

    # --- Front/back depth split ---
    # Forehead is flatter (less depth), occiput is rounder (more depth).
    front_depth = half_depth * 0.85
    back_depth = half_depth * 1.15

    # Adjust back depth from ear-to-ear-back arc
    expected_back_arc = _half_ellipse_arc(half_width, half_depth)
    if expected_back_arc > 0:
        back_ratio = (ear_to_ear_back_mm / 2.0) / expected_back_arc
        back_ratio = max(0.85, min(1.15, back_ratio))
        back_depth *= back_ratio

    # --- Occipital bump ---
    occipital_bump_height = 0.25
    occipital_bump_strength = half_depth * 0.08

    # --- Generate vertex rings ---
    vertex_coords = []

    for j in range(v_segments):
        t = j / (v_segments - 1) if v_segments > 1 else 0.0

        # Height: sine curve gives steep sides, flat dome
        z = height * math.sin(t * math.pi / 2.0)

        # Profile factors at this height
        w_factor = _width_profile(t)
        d_factor = _depth_profile(t)

        local_half_width = half_width * w_factor
        local_front = front_depth * d_factor
        local_back = back_depth * d_factor

        # Occipital bump
        bump_influence = math.exp(
            -((t - occipital_bump_height) ** 2) / (2.0 * 0.08 ** 2)
        )
        local_back += occipital_bump_strength * bump_influence

        # Forehead flattening
        if t < 0.4:
            forehead_flatten = 0.40 * (1.0 - _smoothstep(t / 0.4))
        else:
            forehead_flatten = 0.0

        # Crown Y offset (slightly behind center)
        crown_y_offset = -half_depth * 0.05 * _smoothstep(t)

        # Local forehead/nape widths
        local_forehead_half = forehead_half * w_factor
        local_nape_half = nape_half * w_factor

        # --- Generate ring ---
        for i in range(u_segments):
            u = (i / u_segments) * 2.0 * math.pi
            cos_u = math.cos(u)
            sin_u = math.sin(u)

            front_factor = max(0.0, sin_u)
            back_factor = max(0.0, -sin_u)

            # X (left-right)
            x = local_half_width * cos_u

            # Forehead narrowing
            if front_factor > 0.01 and abs(x) > local_forehead_half:
                blend = front_factor * _smoothstep(max(0, 1.0 - t * 2.0)) * 0.70
                target_x = math.copysign(local_forehead_half, x)
                x = _lerp(x, target_x, blend)

            # Nape narrowing
            if back_factor > 0.01 and abs(x) > local_nape_half:
                blend = back_factor * _smoothstep(max(0, 1.0 - t * 2.0)) * 0.70
                target_x = math.copysign(local_nape_half, x)
                x = _lerp(x, target_x, blend)

            # Y (front-back)
            if sin_u >= 0:
                y = local_front * sin_u * (1.0 - forehead_flatten * front_factor)
            else:
                y = local_back * sin_u

            y += crown_y_offset

            vertex_coords.append((x, y, z))

    # --- Build bmesh ---
    bm = bmesh.new()

    verts = []
    for co in vertex_coords:
        verts.append(bm.verts.new(co))

    # Crown pole at top ring height, slightly behind center
    top_ring_start = (v_segments - 1) * u_segments
    top_ring_z = vertex_coords[top_ring_start][2]
    pole = bm.verts.new((0.0, -half_depth * 0.06, top_ring_z))
    bm.verts.ensure_lookup_table()

    # Quad faces between rings
    for j in range(v_segments - 1):
        for i in range(u_segments):
            i_next = (i + 1) % u_segments
            v0 = j * u_segments + i
            v1 = j * u_segments + i_next
            v2 = (j + 1) * u_segments + i_next
            v3 = (j + 1) * u_segments + i
            bm.faces.new([verts[v0], verts[v1], verts[v2], verts[v3]])

    # Triangle fan to pole
    for i in range(u_segments):
        i_next = (i + 1) % u_segments
        bm.faces.new([verts[top_ring_start + i], verts[top_ring_start + i_next], pole])

    # Bottom cap
    equator_verts = [verts[i] for i in range(u_segments)]
    bm.faces.new(list(reversed(equator_verts)))

    # Validate
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.1)

    return bm
