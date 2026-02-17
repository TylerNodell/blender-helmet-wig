"""Parametric head mesh generator from tape measurements.

Generates a modified superellipsoid approximating a human head shape,
using 10 tape measurements as input. All internal math is in millimeters.
"""

import math
import bmesh


def _spower(base, exp):
    """Signed power: preserves sign for negative base values."""
    return math.copysign(abs(base) ** exp, base) if base != 0.0 else 0.0


def _half_ellipse_arc(a, b):
    """Approximate half-perimeter of an ellipse using Ramanujan's formula.

    Args:
        a: Semi-axis length.
        b: Semi-axis length.

    Returns:
        Approximate arc length of half the ellipse perimeter.
    """
    h = ((a - b) / (a + b)) ** 2 if (a + b) > 0 else 0
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h))) / 2.0


def _superellipse_arc(a, b, n, num_samples=200):
    """Numerically compute the arc length of one quarter of a superellipse.

    The quarter arc goes from (a, 0) to (0, b) for the superellipse
    |x/a|^n + |y/b|^n = 1.

    Args:
        a: Semi-axis in x.
        b: Semi-axis in y.
        n: Superellipse exponent (2.0 = regular ellipse).
        num_samples: Integration resolution.

    Returns:
        Arc length of one quarter of the superellipse.
    """
    length = 0.0
    prev_x, prev_y = a, 0.0
    for i in range(1, num_samples + 1):
        t = (i / num_samples) * (math.pi / 2.0)
        x = a * _spower(math.cos(t), 2.0 / n)
        y = b * _spower(math.sin(t), 2.0 / n)
        dx = x - prev_x
        dy = y - prev_y
        length += math.sqrt(dx * dx + dy * dy)
        prev_x, prev_y = x, y
    return length


def _find_exponent(measured_half_arc, a, b, tol=0.5):
    """Find superellipse exponent that produces the measured half-arc length.

    Uses bisection search. A half-arc is one quarter of the full superellipse
    (e.g., front half of the sagittal profile = forehead-to-crown).

    Args:
        measured_half_arc: Target arc length for one quarter of the curve.
        a: Semi-axis in one direction.
        b: Semi-axis in the other direction.
        tol: Tolerance in mm.

    Returns:
        Exponent value, clamped to [1.0, 6.0].
    """
    lo, hi = 1.0, 6.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        arc = _superellipse_arc(a, b, mid)
        if abs(arc - measured_half_arc) < tol:
            break
        if arc > measured_half_arc:
            # Higher exponent = boxier = longer arc; go lower
            lo = mid
        else:
            hi = mid
    return max(1.0, min(6.0, (lo + hi) / 2.0))


def _smoothstep(t):
    """Hermite smoothstep for C1-continuous blending."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


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
    v_segments=32,
):
    """Generate a parametric head mesh from tape measurements.

    Coordinate system: X = left-right, Y = front-back (positive = front),
    Z = up. Origin at center of head at ear-top level.

    Args:
        head_circumference_mm: Circumference at widest point.
        front_to_back_arc_mm: Arc from forehead hairline over crown to nape.
        ear_to_ear_over_mm: Arc from ear to ear over the top.
        ear_to_ear_back_mm: Arc from ear to ear around the back.
        head_width_mm: Straight-line side-to-side width.
        head_depth_mm: Straight-line front-to-back depth.
        head_height_mm: Straight-line ear-top to crown height.
        forehead_width_mm: Temple-to-temple width.
        nape_width_mm: Width at nape of neck.
        forehead_height_mm: Hairline to brow ridge.
        u_segments: Longitudinal resolution (around the head).
        v_segments: Latitudinal resolution (bottom to top).

    Returns:
        bmesh.types.BMesh: Closed, manifold mesh representing the head shape.
    """
    # --- Step 1: Base radii ---
    rx = head_width_mm / 2.0      # lateral (X)
    ry = head_depth_mm / 2.0      # anterior-posterior (Y)
    rz = head_height_mm           # vertical (Z)

    # --- Step 2: Circumference cross-check ---
    # Scale rx and ry proportionally so the equatorial ellipse matches
    # the measured circumference.
    expected_circ = 2.0 * _half_ellipse_arc(rx, ry)
    if expected_circ > 0:
        circ_ratio = head_circumference_mm / expected_circ
        rx *= circ_ratio
        ry *= circ_ratio

    # --- Step 3: Compute superellipsoid exponents from arcs ---
    # Front-to-back arc spans the full sagittal profile (half = front or back).
    # We use the full arc = 2 quarter-arcs through (ry, rz).
    sagittal_quarter = front_to_back_arc_mm / 2.0
    n_sagittal = _find_exponent(sagittal_quarter, ry, rz)

    # Ear-to-ear over top: full coronal arc = 2 quarter-arcs through (rx, rz).
    coronal_quarter = ear_to_ear_over_mm / 2.0
    n_coronal = _find_exponent(coronal_quarter, rx, rz)

    # Ear-to-ear around back: controls posterior bulge.
    # Compare with the expected back-half coronal arc to get a roundness factor.
    back_quarter = ear_to_ear_back_mm / 2.0
    expected_back_quarter = _superellipse_arc(rx, ry, 2.0)
    back_roundness = back_quarter / expected_back_quarter if expected_back_quarter > 0 else 1.0

    # --- Step 4: Generate vertices ---
    vertex_coords = []

    forehead_half = forehead_width_mm / 2.0
    nape_half = nape_width_mm / 2.0

    for j in range(v_segments):
        v = (j / v_segments) * (math.pi / 2.0)
        cos_v = math.cos(v)
        sin_v = math.sin(v)

        for i in range(u_segments):
            u = (i / u_segments) * (2.0 * math.pi)
            cos_u = math.cos(u)
            sin_u = math.sin(u)

            # Front/back blend factors
            # Convention: u=0 is +X (right side), u=pi/2 is +Y (front)
            front_factor = max(0.0, sin_u)   # 1.0 at front, 0.0 at sides/back
            back_factor = max(0.0, -sin_u)   # 1.0 at back, 0.0 at sides/front

            # Local Y radius: adjust posterior region for roundness
            ry_local = ry * (1.0 + (back_roundness - 1.0) * back_factor)

            # Use appropriate exponents blended by region
            # Sagittal exponent dominates in front/back, coronal in sides
            n_local = n_sagittal * (front_factor + back_factor) + n_coronal * (1.0 - front_factor - back_factor)
            n_local = max(1.0, n_local)

            # Base superellipsoid vertex
            x = rx * _spower(cos_v, 2.0 / n_coronal) * _spower(cos_u, 2.0 / n_local)
            y = ry_local * _spower(cos_v, 2.0 / n_sagittal) * _spower(sin_u, 2.0 / n_local)
            z = rz * _spower(sin_v, 2.0 / n_sagittal)

            # --- Step 5: Contour refinement ---
            # Height blend: strongest at bottom (z near 0), fades toward crown
            height_blend = _smoothstep(1.0 - sin_v) if rz > 0 else 0.0

            # Forehead narrowing (front region, lower portion)
            if front_factor > 0.01 and abs(x) > forehead_half:
                narrow_blend = height_blend * front_factor
                target_x = math.copysign(forehead_half, x)
                x = x * (1.0 - narrow_blend) + target_x * narrow_blend

            # Nape narrowing (back region, lower portion)
            if back_factor > 0.01 and abs(x) > nape_half:
                narrow_blend = height_blend * back_factor
                target_x = math.copysign(nape_half, x)
                x = x * (1.0 - narrow_blend) + target_x * narrow_blend

            vertex_coords.append((x, y, z))

    # --- Step 6: Build bmesh ---
    bm = bmesh.new()

    # Add vertices
    verts = []
    for co in vertex_coords:
        verts.append(bm.verts.new(co))

    # Add pole vertex (top of head)
    pole = bm.verts.new((0.0, 0.0, rz))
    bm.verts.ensure_lookup_table()

    # Add quad faces for the grid
    for j in range(v_segments - 1):
        for i in range(u_segments):
            i_next = (i + 1) % u_segments
            v0 = j * u_segments + i
            v1 = j * u_segments + i_next
            v2 = (j + 1) * u_segments + i_next
            v3 = (j + 1) * u_segments + i
            bm.faces.new([verts[v0], verts[v1], verts[v2], verts[v3]])

    # Triangle fan to pole from the top row
    top_row_start = (v_segments - 1) * u_segments
    for i in range(u_segments):
        i_next = (i + 1) % u_segments
        v0 = top_row_start + i
        v1 = top_row_start + i_next
        bm.faces.new([verts[v0], verts[v1], pole])

    # --- Step 7: Close the bottom (equator cap) ---
    equator_verts = [verts[i] for i in range(u_segments)]
    bm.faces.new(list(reversed(equator_verts)))

    # --- Step 8: Validate ---
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.01)

    return bm
