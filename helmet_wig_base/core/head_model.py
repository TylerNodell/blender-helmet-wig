"""Parametric head mesh generator from tape measurements.

Generates a head-shaped mesh using profile-based cross-section lofting
with anatomical deformations. All math in millimeters.

Key anatomical features modeled:
- Oblong egg shape: longer front-to-back than side-to-side
- Flatter on top and sides, rounder in the back (depth holds fuller)
- Width profile tapers sooner (exponent 1.8) → flatter sides
- Depth profile holds fuller (exponent 3.0) → oblong front-to-back
- Front/back asymmetry: forehead flatter (80%), occiput rounder (120%)
- Crown sits slightly behind center
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
    """Width factor across the full head height.

    t can be negative (below ear level) or positive (above ear level).
    t=0 is ear level, t=1 is crown.

    Returns 0..1 where 1 = full width.

    Above ear level: elliptical curve sqrt(1 - t^1.8)
    The lower exponent (1.8) makes the width taper sooner than depth,
    creating a head that is flatter on the sides — narrower side-to-side
    in the upper half compared to the front-to-back dimension.
    Below ear level: tapers inward (head narrows toward jaw/neck)
    """
    if t < 0:
        # Below ear level: taper inward. At t=-0.3 we're about 70% width.
        return max(0.3, 1.0 + t * 1.0)  # linear taper below ears
    return math.sqrt(max(0.0, 1.0 - t ** 1.8))


def _depth_profile(t):
    """Depth factor across the full head height.

    Uses a higher exponent (3.0) than the width profile so that
    front-to-back depth stays fuller much higher up the dome. This
    creates the characteristic oblong/egg shape of a human head:
    longer front-to-back than side-to-side, especially in the upper half.

    At t=0.5: depth factor ≈ 0.97 vs width factor ≈ 0.84
    At t=0.7: depth factor ≈ 0.90 vs width factor ≈ 0.70

    Below ear level: tapers less aggressively (back of head stays round).
    """
    if t < 0:
        return max(0.4, 1.0 + t * 0.8)
    return math.sqrt(max(0.0, 1.0 - t ** 3.0))


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
    # The 0.80/1.20 split creates a noticeably egg-shaped profile where
    # the back of the head protrudes more than the front.
    front_depth = half_depth * 0.80
    back_depth = half_depth * 1.20

    # Adjust back depth from ear-to-ear-back arc
    expected_back_arc = _half_ellipse_arc(half_width, half_depth)
    if expected_back_arc > 0:
        back_ratio = (ear_to_ear_back_mm / 2.0) / expected_back_arc
        back_ratio = max(0.85, min(1.15, back_ratio))
        back_depth *= back_ratio

    # Note: the front/back depth split (0.85 / 1.15) already models the
    # rounder occiput vs flatter forehead. No additional bump needed.

    # --- Generate vertex rings ---
    # The mesh extends from below ear level (t_min) to crown (t=1).
    # t=0 is ear-top level (Z=0), t<0 is below ears, t=1 is crown.
    # This extra below-ear geometry lets the helmet edge extend down
    # to cover the nape, ears, and occipital area.
    t_min = -0.30  # 30% of head height below ear level
    vertex_coords = []

    for j in range(v_segments):
        t = t_min + (1.0 - t_min) * (j / (v_segments - 1)) if v_segments > 1 else 0.0

        # Z position: t=0 → Z=0 (ear level), t=1 → Z=height (crown)
        # t<0 → Z<0 (below ears)
        z = height * t

        # Profile factors at this height
        w_factor = _width_profile(t)
        d_factor = _depth_profile(t)

        local_half_width = half_width * w_factor
        local_front = front_depth * d_factor
        local_back = back_depth * d_factor

        # Forehead flattening — subtly flattens the front curve shape
        # without significantly reducing the overall depth.
        # Strength 0.15 means at most 15% compression of front Y.
        if t < 0.35:
            forehead_flatten = 0.15 * (1.0 - _smoothstep(t / 0.35))
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
