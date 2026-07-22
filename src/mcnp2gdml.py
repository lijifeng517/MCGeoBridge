import argparse
import json
import math
import os
import random
import re
from typing import List, Tuple

from mcnp import MModel
from mcnp.MExprParser import SurfaceRef, CellRef, UnionNode, IntersectionNode, ComplementNode, expr_to_str
from mcnp.MSurface import MSurfType, MSurface
from gdml import GModel, GConstant, GVector
from gdml import GElement, GIsotope, GMixture
from gdml import GBox, GSphere, GTube, GTorus, GGenericPolycone, GEllipticalTube, GEllipsoid, GCons, GPolyhedra, GBooleanSolid
from gdml import GVolume, GPhysicalVolume


DEFAULT_HALF = 1000.0


class EvalSolid:
    def contains(self, p, eps=1e-9) -> bool:
        raise NotImplementedError()


class EvalBox(EvalSolid):
    def __init__(self, xlen, ylen, zlen):
        self.hx = xlen / 2.0
        self.hy = ylen / 2.0
        self.hz = zlen / 2.0

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        return (abs(x) <= self.hx + eps and abs(y) <= self.hy + eps and abs(z) <= self.hz + eps)


class EvalTube(EvalSolid):
    def __init__(self, rmax, zlen, rmin=0.0):
        self.rmax = rmax
        self.rmin = rmin
        self.hz = zlen / 2.0

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        r2 = x * x + y * y
        return (self.rmin * self.rmin - eps <= r2 <= self.rmax * self.rmax + eps) and (abs(z) <= self.hz + eps)


class EvalSphere(EvalSolid):
    def __init__(self, rmax, rmin=0.0):
        self.rmax = rmax
        self.rmin = rmin

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        r2 = x * x + y * y + z * z
        return (self.rmin * self.rmin - eps <= r2 <= self.rmax * self.rmax + eps)


class EvalTorus(EvalSolid):
    def __init__(self, rtor, rmax, rmin=0.0):
        self.rtor = float(rtor)
        self.rmax = float(rmax)
        self.rmin = float(rmin)

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        q = math.sqrt(x * x + y * y) - self.rtor
        tube_r2 = q * q + z * z
        return self.rmin * self.rmin - eps <= tube_r2 <= self.rmax * self.rmax + eps


class EvalEllipticalTube(EvalSolid):
    def __init__(self, dx, dy, dz):
        self.dx = float(dx)
        self.dy = float(dy)
        self.dz = float(dz)

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        radial = (x / self.dx) ** 2 + (y / self.dy) ** 2
        return radial <= 1.0 + eps and abs(z) <= self.dz + eps


class EvalEllipsoid(EvalSolid):
    def __init__(self, ax, by, cz):
        self.ax = float(ax)
        self.by = float(by)
        self.cz = float(cz)

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        value = (x / self.ax) ** 2 + (y / self.by) ** 2 + (z / self.cz) ** 2
        return value <= 1.0 + eps


class EvalCons(EvalSolid):
    def __init__(self, r1, r2, zlen):
        self.r1 = float(r1)
        self.r2 = float(r2)
        self.hz = float(zlen) / 2.0

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        if abs(z) > self.hz + eps:
            return False
        t = (z + self.hz) / (2.0 * self.hz) if self.hz > 0.0 else 0.0
        radius = self.r1 + t * (self.r2 - self.r1)
        return x * x + y * y <= radius * radius + eps


class EvalHexPrism(EvalSolid):
    def __init__(self, rmax, zlen, startphi_deg=0.0):
        self.rmax = float(rmax)
        self.hz = float(zlen) / 2.0
        self.start = math.radians(float(startphi_deg))
        self.verts = []
        for k in range(6):
            a = self.start + k * (math.pi / 3.0)
            self.verts.append((self.rmax * math.cos(a), self.rmax * math.sin(a)))

    def contains(self, p, eps=1e-9) -> bool:
        x, y, z = p
        if abs(z) > self.hz + eps:
            return False
        n = len(self.verts)
        for i in range(n):
            x1, y1 = self.verts[i]
            x2, y2 = self.verts[(i + 1) % n]
            ex, ey = (x2 - x1), (y2 - y1)
            cross = (x - x1) * ey - (y - y1) * ex
            # Vertices are generated counter-clockwise.  Interior points lie
            # on the right-hand side of each directed edge under the cross
            # product convention used here.
            if cross > eps:
                return False
        return True


class EvalBoolean(EvalSolid):
    def __init__(self, op, left: EvalSolid, right: EvalSolid, pos, rot):
        self.op = op
        self.left = left
        self.right = right
        self.pos = pos
        self.rot = rot

    def contains(self, p, eps=1e-9) -> bool:
        left_in = self.left.contains(p, eps)
        pr = _apply_inverse_transform(p, self.pos, self.rot)
        right_in = self.right.contains(pr, eps)
        if self.op == "union":
            return left_in or right_in
        if self.op == "intersection":
            return left_in and right_in
        if self.op == "subtraction":
            return left_in and (not right_in)
        raise ValueError(f"Unknown boolean op {self.op}")


def _rot_x(p, ang):
    x, y, z = p
    c = math.cos(ang)
    s = math.sin(ang)
    return (x, y * c - z * s, y * s + z * c)


def _rot_y(p, ang):
    x, y, z = p
    c = math.cos(ang)
    s = math.sin(ang)
    return (x * c + z * s, y, -x * s + z * c)


def _rot_z(p, ang):
    x, y, z = p
    c = math.cos(ang)
    s = math.sin(ang)
    return (x * c - y * s, x * s + y * c, z)


def _apply_inverse_transform(p, pos, rot):
    x, y, z = p
    x -= pos[0]
    y -= pos[1]
    z -= pos[2]
    rx, ry, rz = [math.radians(r) for r in rot]
    # inverse: rotate by -rz, -ry, -rx in reverse order
    x, y, z = _rot_z((x, y, z), -rz)
    x, y, z = _rot_y((x, y, z), -ry)
    x, y, z = _rot_x((x, y, z), -rx)
    return (x, y, z)


def _apply_transform(p, pos, rot):
    """Apply the forward rigid transform used by GDML placements."""
    matrix = _euler_deg_to_matrix_zyx(rot)
    q = _mat_vec_mul(matrix, p)
    return (q[0] + pos[0], q[1] + pos[1], q[2] + pos[2])


def _dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm3(v):
    return math.sqrt(_dot3(v, v))


def _cross3(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit3(v):
    n = _norm3(v)
    if n <= 0.0:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _axis_aligned(h, eps=1e-9):
    hx, hy, hz = h
    if abs(hy) <= eps and abs(hz) <= eps and abs(hx) > eps:
        return "x", abs(hx), 1.0 if hx >= 0 else -1.0
    if abs(hx) <= eps and abs(hz) <= eps and abs(hy) > eps:
        return "y", abs(hy), 1.0 if hy >= 0 else -1.0
    if abs(hx) <= eps and abs(hy) <= eps and abs(hz) > eps:
        return "z", abs(hz), 1.0 if hz >= 0 else -1.0
    return None, 0.0, 1.0


def _rotation_from_z(direction):
    """Return a ZYX Euler rotation that maps local +Z onto direction."""
    e3 = _unit3(direction)
    if _norm3(e3) <= 0.0:
        raise ValueError(f"Cannot orient a solid along zero vector {direction}")
    helper = (0.0, 0.0, 1.0) if abs(e3[2]) < 0.9 else (1.0, 0.0, 0.0)
    e1 = _unit3(_cross3(helper, e3))
    e2 = _cross3(e3, e1)
    matrix = [
        [e1[0], e2[0], e3[0]],
        [e1[1], e2[1], e3[1]],
        [e1[2], e2[2], e3[2]],
    ]
    return _matrix_to_euler_deg_zyx(matrix)


def _hex_face_angle_deg(axis, u):
    ux, uy, uz = u
    if axis == "x":
        lx, ly = -uz, uy
    elif axis == "y":
        lx, ly = ux, -uz
    else:
        lx, ly = ux, uy
    return math.degrees(math.atan2(ly, lx))


def _point_in_regular_hex_local(x, y, rmax, startphi_deg, eps=1e-9):
    verts = []
    base = math.radians(startphi_deg)
    for k in range(6):
        a = base + k * (math.pi / 3.0)
        verts.append((rmax * math.cos(a), rmax * math.sin(a)))
    for i in range(6):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % 6]
        ex, ey = (x2 - x1), (y2 - y1)
        if (x - x1) * ey - (y - y1) * ex < -eps:
            return False
    return True


def _euler_deg_to_matrix_zyx(rot):
    rx, ry, rz = [math.radians(float(v)) for v in rot]
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    # R = Rz * Ry * Rx
    return [
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy, cy * sx, cy * cx],
    ]


def _matrix_to_euler_deg_zyx(m):
    r20 = max(-1.0, min(1.0, m[2][0]))
    ry = math.asin(-r20)
    cy = math.cos(ry)
    if abs(cy) > 1e-10:
        rx = math.atan2(m[2][1], m[2][2])
        rz = math.atan2(m[1][0], m[0][0])
    else:
        rx = 0.0
        rz = math.atan2(-m[0][1], m[1][1])
    return (math.degrees(rx), math.degrees(ry), math.degrees(rz))


def _mat_mul(a, b):
    return [
        [a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
         a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
         a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2]],
        [a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
         a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
         a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2]],
        [a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
         a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
         a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2]],
    ]


def _mat_vec_mul(m, v):
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _compose_pose(parent_pos, parent_rot, local_pos, local_rot):
    rp = _euler_deg_to_matrix_zyx(parent_rot)
    rl = _euler_deg_to_matrix_zyx(local_rot)
    r = _mat_mul(rp, rl)
    t_local = _mat_vec_mul(rp, local_pos)
    t = (parent_pos[0] + t_local[0], parent_pos[1] + t_local[1], parent_pos[2] + t_local[2])
    rot = list(_matrix_to_euler_deg_zyx(r))
    for i, a in enumerate(rot):
        a = ((a + 180.0) % 360.0) - 180.0
        if abs(a) < 1e-8:
            a = 0.0
        rot[i] = a
    return t, (rot[0], rot[1], rot[2])


def _relative_pose(parent_pos, parent_rot, child_pos, child_rot):
    """Return the child pose in the coordinate system of the parent pose."""
    rp = _euler_deg_to_matrix_zyx(parent_rot)
    rc = _euler_deg_to_matrix_zyx(child_rot)
    rp_t = [
        [rp[0][0], rp[1][0], rp[2][0]],
        [rp[0][1], rp[1][1], rp[2][1]],
        [rp[0][2], rp[1][2], rp[2][2]],
    ]
    delta = (
        child_pos[0] - parent_pos[0],
        child_pos[1] - parent_pos[1],
        child_pos[2] - parent_pos[2],
    )
    pos = _mat_vec_mul(rp_t, delta)
    rot = list(_matrix_to_euler_deg_zyx(_mat_mul(rp_t, rc)))
    for i, angle in enumerate(rot):
        angle = ((angle + 180.0) % 360.0) - 180.0
        if abs(angle) < 1e-8:
            angle = 0.0
        rot[i] = angle
    return pos, (rot[0], rot[1], rot[2])


def _parse_transform_from_raw(raw: str, tr_map, is_star: bool = False):
    txt = str(raw).strip()
    if not txt:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    txt = txt.replace(",", " ").replace("(", " ").replace(")", " ")
    toks = [t for t in txt.split() if t]
    if len(toks) == 1 and re.fullmatch(r"[+-]?\d+", toks[0]):
        tid = int(toks[0])
        td = tr_map.get(tid)
        if isinstance(td, dict):
            return tuple(td.get("pos", (0.0, 0.0, 0.0))), tuple(td.get("rot", (0.0, 0.0, 0.0)))
        if isinstance(td, (list, tuple)) and len(td) >= 3:
            return (td[0], td[1], td[2]), (0.0, 0.0, 0.0)
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    vals = []
    for t in toks:
        try:
            vals.append(float(t))
        except Exception:
            pass
    if len(vals) >= 9:
        pos = (vals[0], vals[1], vals[2])
        direction_values = vals[3:12]
        if is_star:
            direction_values = [math.cos(math.radians(v)) for v in direction_values]
        if len(direction_values) < 9:
            # MCNP permits two direction-cosine vectors and derives the third.
            b1, b2, b3, b4, b5, b6 = direction_values
            cx = b2 * b6 - b3 * b5
            cy = b3 * b4 - b1 * b6
            cz = b1 * b5 - b2 * b4
            cn = math.sqrt(cx * cx + cy * cy + cz * cz)
            if cn > 1e-14:
                cx, cy, cz = cx / cn, cy / cn, cz / cn
            b7, b8, b9 = cx, cy, cz
        else:
            b1, b2, b3, b4, b5, b6, b7, b8, b9 = direction_values[:9]
        m = [[b1, b4, b7], [b2, b5, b8], [b3, b6, b9]]
        rot = _matrix_to_euler_deg_zyx(m)
        return pos, rot
    if len(vals) >= 6:
        return (vals[0], vals[1], vals[2]), (vals[3], vals[4], vals[5])
    if len(vals) >= 3:
        return (vals[0], vals[1], vals[2]), (0.0, 0.0, 0.0)
    return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)


def _eval_surface(surf, sense, p, eps=1e-9) -> bool:
    x, y, z = p
    if surf.stype == MSurfType.P:
        if len(surf.params) < 4:
            raise ValueError(f"Invalid P parameters for surface {surf.sid}: {surf.params}")
        a, b, c, d = surf.params[0:4]
        value = a * x + b * y + c * z - d
        return value <= eps if sense < 0 else value >= -eps
    if surf.stype == MSurfType.PX:
        return x <= surf.params[0] + eps if sense < 0 else x >= surf.params[0] - eps
    if surf.stype == MSurfType.PY:
        return y <= surf.params[0] + eps if sense < 0 else y >= surf.params[0] - eps
    if surf.stype == MSurfType.PZ:
        return z <= surf.params[0] + eps if sense < 0 else z >= surf.params[0] - eps
    if surf.stype in (MSurfType.TX, MSurfType.TY, MSurfType.TZ):
        if len(surf.params) < 6:
            raise ValueError(f"Invalid torus parameters for surface {surf.sid}: {surf.params}")
        x0, y0, z0, major, axial_minor, radial_minor = surf.params[0:6]
        dx, dy, dz = x - x0, y - y0, z - z0
        if axial_minor <= 0.0 or radial_minor <= 0.0:
            raise ValueError(f"Invalid torus minor radii for surface {surf.sid}: {surf.params}")
        if surf.stype == MSurfType.TX:
            axial = dx
            radial = math.sqrt(dy * dy + dz * dz)
        elif surf.stype == MSurfType.TY:
            axial = dy
            radial = math.sqrt(dx * dx + dz * dz)
        else:
            axial = dz
            radial = math.sqrt(dx * dx + dy * dy)
        value = ((radial - major) / radial_minor) ** 2 + (axial / axial_minor) ** 2
        return value <= 1.0 + eps if sense < 0 else value >= 1.0 - eps
    if surf.stype == MSurfType.SQ:
        if len(surf.params) < 10:
            raise ValueError(f"Invalid SQ parameters for surface {surf.sid}: {surf.params}")
        a, b, c, d, e, f, g, x0, y0, z0 = surf.params[0:10]
        xx, yy, zz = x - x0, y - y0, z - z0
        value = a * xx * xx + b * yy * yy + c * zz * zz + 2*d*xx + 2*e*yy + 2*f*zz + g
        return value <= eps if sense < 0 else value >= -eps
    if surf.stype == MSurfType.GQ:
        if len(surf.params) < 10:
            raise ValueError(f"Invalid GQ parameters for surface {surf.sid}: {surf.params}")
        a, b, c, d, e, f, g, h, j, k = surf.params[0:10]
        value = (
            a*x*x + b*y*y + c*z*z + d*x*y + e*y*z + f*z*x
            + g*x + h*y + j*z + k
        )
        return value <= eps if sense < 0 else value >= -eps
    if surf.stype == MSurfType.ELL_G:
        if len(surf.params) < 15:
            raise ValueError(f"Invalid ellipsoid parameters for surface {surf.sid}: {surf.params}")
        center = tuple(surf.params[0:3])
        axes = tuple(_unit3(tuple(surf.params[i:i+3])) for i in (3, 6, 9))
        radii = surf.params[12:15]
        delta = (x - center[0], y - center[1], z - center[2])
        value = sum((_dot3(delta, axis) / radius) ** 2 for axis, radius in zip(axes, radii))
        return value <= 1.0 + eps if sense < 0 else value >= 1.0 - eps
    if surf.stype == MSurfType.ECYL_G:
        if len(surf.params) < 14:
            raise ValueError(f"Invalid elliptical-cylinder parameters for surface {surf.sid}: {surf.params}")
        center = tuple(surf.params[0:3])
        e1 = _unit3(tuple(surf.params[3:6]))
        e2 = _unit3(tuple(surf.params[6:9]))
        r1, r2 = surf.params[12:14]
        delta = (x - center[0], y - center[1], z - center[2])
        value = (_dot3(delta, e1) / r1) ** 2 + (_dot3(delta, e2) / r2) ** 2
        return value <= 1.0 + eps if sense < 0 else value >= 1.0 - eps
    if surf.stype in (
        MSurfType.KX, MSurfType.KY, MSurfType.KZ,
        MSurfType.K_X, MSurfType.K_Y, MSurfType.K_Z,
    ):
        vertex, axis, t2, sheet = _cone_surface_parameters(surf)
        delta = (x - vertex[0], y - vertex[1], z - vertex[2])
        axial = _dot3(delta, axis)
        radial = tuple(delta[i] - axial * axis[i] for i in range(3))
        allowed_sheet = sheet == 0 or (sheet > 0 and axial >= -eps) or (sheet < 0 and axial <= eps)
        inside = allowed_sheet and _dot3(radial, radial) <= t2 * axial * axial + eps
        return inside if sense < 0 else (not inside)
    if surf.stype == MSurfType.CONE_G:
        vertex, axis, t2, sheet = _cone_surface_parameters(surf)
        delta = (x - vertex[0], y - vertex[1], z - vertex[2])
        axial = _dot3(delta, axis)
        radial = tuple(delta[i] - axial * axis[i] for i in range(3))
        allowed_sheet = sheet == 0 or (sheet > 0 and axial >= -eps) or (sheet < 0 and axial <= eps)
        inside = allowed_sheet and _dot3(radial, radial) <= t2 * axial * axial + eps
        return inside if sense < 0 else (not inside)
    if surf.stype == MSurfType.CX:
        r2 = y * y + z * z
        return r2 <= surf.params[0] * surf.params[0] + eps if sense < 0 else r2 >= surf.params[0] * surf.params[0] - eps
    if surf.stype == MSurfType.C_X:
        y0, z0, r = surf.params[0:3]
        r2 = (y - y0) * (y - y0) + (z - z0) * (z - z0)
        return r2 <= r * r + eps if sense < 0 else r2 >= r * r - eps
    if surf.stype == MSurfType.CY:
        r2 = x * x + z * z
        return r2 <= surf.params[0] * surf.params[0] + eps if sense < 0 else r2 >= surf.params[0] * surf.params[0] - eps
    if surf.stype == MSurfType.C_Y:
        x0, z0, r = surf.params[0:3]
        r2 = (x - x0) * (x - x0) + (z - z0) * (z - z0)
        return r2 <= r * r + eps if sense < 0 else r2 >= r * r - eps
    if surf.stype == MSurfType.CZ:
        r2 = x * x + y * y
        return r2 <= surf.params[0] * surf.params[0] + eps if sense < 0 else r2 >= surf.params[0] * surf.params[0] - eps
    if surf.stype == MSurfType.C_Z:
        x0, y0, r = surf.params[0:3]
        r2 = (x - x0) * (x - x0) + (y - y0) * (y - y0)
        return r2 <= r * r + eps if sense < 0 else r2 >= r * r - eps
    if surf.stype == MSurfType.C_G:
        if len(surf.params) < 7:
            raise ValueError(f"Invalid general cylinder parameters for surface {surf.sid}: {surf.params}")
        x0, y0, z0, ax, ay, az, r = surf.params[0:7]
        axis = _unit3((ax, ay, az))
        d = (x - x0, y - y0, z - z0)
        axial = _dot3(d, axis)
        radial = (d[0] - axial * axis[0], d[1] - axial * axis[1], d[2] - axial * axis[2])
        r2 = _dot3(radial, radial)
        return r2 <= r * r + eps if sense < 0 else r2 >= r * r - eps
    if surf.stype == MSurfType.SO:
        r2 = x * x + y * y + z * z
        return r2 <= surf.params[0] * surf.params[0] + eps if sense < 0 else r2 >= surf.params[0] * surf.params[0] - eps
    if surf.stype == MSurfType.SPH:
        if len(surf.params) >= 4:
            x0, y0, z0, r = surf.params[0:4]
        elif len(surf.params) == 1:
            x0, y0, z0, r = 0.0, 0.0, 0.0, surf.params[0]
        else:
            raise ValueError(f"Invalid SPH parameters for surface {surf.sid}: {surf.params}")
        dx, dy, dz = x - x0, y - y0, z - z0
        r2 = dx * dx + dy * dy + dz * dz
        return r2 <= r * r + eps if sense < 0 else r2 >= r * r - eps
    if surf.stype == MSurfType.RPP:
        x0, x1, y0, y1, z0, z1 = surf.params[0:6]
        xmin, xmax = min(x0, x1), max(x0, x1)
        ymin, ymax = min(y0, y1), max(y0, y1)
        zmin, zmax = min(z0, z1), max(z0, z1)
        inside = (
            xmin - eps <= x <= xmax + eps
            and ymin - eps <= y <= ymax + eps
            and zmin - eps <= z <= zmax + eps
        )
        return inside if sense < 0 else (not inside)
    if surf.stype == MSurfType.RCC:
        x0, y0, z0, hx, hy, hz, r = surf.params[0:7]
        h = (hx, hy, hz)
        L = _norm3(h)
        if L <= eps:
            return False
        e3 = (hx / L, hy / L, hz / L)
        d = (x - x0, y - y0, z - z0)
        t = _dot3(d, e3)
        rx, ry, rz = (d[0] - t * e3[0], d[1] - t * e3[1], d[2] - t * e3[2])
        inside = (-eps <= t <= L + eps) and (rx * rx + ry * ry + rz * rz <= r * r + eps)
        return inside if sense < 0 else (not inside)
    if surf.stype == MSurfType.TRC:
        if len(surf.params) < 8:
            raise ValueError(f"Invalid TRC parameters for surface {surf.sid}: {surf.params}")
        x0, y0, z0, hx, hy, hz, r1, r2 = surf.params[0:8]
        h = (hx, hy, hz)
        length = _norm3(h)
        if length <= eps:
            return False
        axis = _unit3(h)
        delta = (x - x0, y - y0, z - z0)
        axial = _dot3(delta, axis)
        radial = tuple(delta[i] - axial * axis[i] for i in range(3))
        t = axial / length
        radius = r1 + t * (r2 - r1)
        inside = -eps <= axial <= length + eps and _dot3(radial, radial) <= radius * radius + eps
        return inside if sense < 0 else (not inside)
    if surf.stype == MSurfType.BOX:
        if len(surf.params) < 12:
            raise ValueError(f"Invalid BOX parameters for surface {surf.sid}: {surf.params}")
        x0, y0, z0, *rest = surf.params[0:12]
        a, b, c = tuple(rest[0:3]), tuple(rest[3:6]), tuple(rest[6:9])
        d = (x - x0, y - y0, z - z0)
        coeffs = []
        for edge in (a, b, c):
            den = _dot3(edge, edge)
            if den <= eps:
                return False
            coeffs.append(_dot3(d, edge) / den)
        inside = all(-eps <= value <= 1.0 + eps for value in coeffs)
        return inside if sense < 0 else (not inside)
    if surf.stype == MSurfType.RHP:
        x0, y0, z0, hx, hy, hz, ux, uy, uz = surf.params[0:9]
        h = (hx, hy, hz)
        L = _norm3(h)
        if L <= eps:
            return False
        e3 = (hx / L, hy / L, hz / L)
        u = (ux, uy, uz)
        ud = _dot3(u, e3)
        up = (u[0] - ud * e3[0], u[1] - ud * e3[1], u[2] - ud * e3[2])
        a = _norm3(up)
        if a <= eps:
            return False
        e1 = (up[0] / a, up[1] / a, up[2] / a)  # face-normal direction
        e2 = _cross3(e3, e1)

        d = (x - x0, y - y0, z - z0)
        t = _dot3(d, e3)
        if t < -eps or t > L + eps:
            inside = False
        else:
            lx = _dot3(d, e1)
            ly = _dot3(d, e2)
            rmax = a / math.cos(math.pi / 6.0)
            inside = _point_in_regular_hex_local(lx, ly, rmax, -30.0, eps)
        return inside if sense < 0 else (not inside)
    raise ValueError(f"Unsupported surface type: {surf.stype}")


def _eval_expr(node, p, surface_map, cell_ast_map, eps=1e-9, stack=None, cell_trcl_map=None) -> bool:
    if stack is None:
        stack = tuple()
    if isinstance(node, SurfaceRef):
        surf = surface_map.get(node.sid)
        if surf is None:
            raise ValueError(f"Surface {node.sid} not found in model")
        return _eval_surface(surf, node.sense, p, eps)
    if isinstance(node, CellRef):
        if node.cid in stack:
            return False
        cell_ast = cell_ast_map.get(node.cid)
        if cell_ast is None:
            raise ValueError(f"Cell {node.cid} not found in model")
        p2 = p
        if cell_trcl_map is not None:
            t = cell_trcl_map.get(node.cid, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
            p2 = _apply_inverse_transform(p, t[0], t[1])
        return _eval_expr(cell_ast, p2, surface_map, cell_ast_map, eps, stack + (node.cid,), cell_trcl_map)
    if isinstance(node, UnionNode):
        return _eval_expr(node.left, p, surface_map, cell_ast_map, eps, stack, cell_trcl_map) or _eval_expr(
            node.right, p, surface_map, cell_ast_map, eps, stack, cell_trcl_map
        )
    if isinstance(node, IntersectionNode):
        return _eval_expr(node.left, p, surface_map, cell_ast_map, eps, stack, cell_trcl_map) and _eval_expr(
            node.right, p, surface_map, cell_ast_map, eps, stack, cell_trcl_map
        )
    if isinstance(node, ComplementNode):
        return not _eval_expr(node.child, p, surface_map, cell_ast_map, eps, stack, cell_trcl_map)
    raise ValueError(f"Unknown expression node type: {type(node)}")


def _iter_surface_refs(node):
    """Yield unique surface references used directly by an expression AST."""
    seen = set()

    def walk(current):
        if isinstance(current, SurfaceRef):
            key = (current.sid, current.sense)
            if key not in seen:
                seen.add(key)
                yield current
            return
        if isinstance(current, (UnionNode, IntersectionNode)):
            yield from walk(current.left)
            yield from walk(current.right)
            return
        if isinstance(current, ComplementNode):
            yield from walk(current.child)

    yield from walk(node)


def _surface_boundary_pairs(surf, bbox, count, delta, rng):
    """Generate deterministic near-boundary point pairs for common surfaces.

    Each item is ``(minus_point, plus_point)`` in the surface coordinate frame.
    Unsupported analytic forms return an empty list and are reported by the
    validation summary instead of being silently treated as exercised.
    """
    cx, cy, cz = bbox["cx"], bbox["cy"], bbox["cz"]
    hx, hy, hz = bbox["hx"], bbox["hy"], bbox["hz"]
    limits = ((cx - hx, cx + hx), (cy - hy, cy + hy), (cz - hz, cz + hz))
    diagonal = 2.0 * math.sqrt(hx * hx + hy * hy + hz * hz)
    pairs = []

    def in_bbox(point):
        return all(limits[i][0] <= point[i] <= limits[i][1] for i in range(3))

    def add(point, normal):
        unit = _unit3(normal)
        if _norm3(unit) <= 0.0:
            return
        minus = tuple(point[i] - delta * unit[i] for i in range(3))
        plus = tuple(point[i] + delta * unit[i] for i in range(3))
        if in_bbox(minus) and in_bbox(plus):
            pairs.append((minus, plus))

    def tangent_basis(axis):
        axis = _unit3(axis)
        helper = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.8 else (0.0, 1.0, 0.0)
        e1 = _unit3(_cross3(axis, helper))
        return e1, _cross3(axis, e1)

    stype = surf.stype
    params = surf.params
    if stype in (MSurfType.P, MSurfType.PX, MSurfType.PY, MSurfType.PZ):
        if stype == MSurfType.P:
            if len(params) < 4:
                return pairs
            normal, offset = tuple(params[0:3]), params[3]
        elif stype == MSurfType.PX:
            normal, offset = (1.0, 0.0, 0.0), params[0]
        elif stype == MSurfType.PY:
            normal, offset = (0.0, 1.0, 0.0), params[0]
        else:
            normal, offset = (0.0, 0.0, 1.0), params[0]
        den = _dot3(normal, normal)
        if den <= 0.0:
            return pairs
        for _ in range(count):
            point = [rng.uniform(*limits[i]) for i in range(3)]
            correction = (_dot3(normal, point) - offset) / den
            point = tuple(point[i] - correction * normal[i] for i in range(3))
            add(point, normal)
        return pairs

    cylinder = None
    if stype == MSurfType.CX:
        cylinder = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), params[0])
    elif stype == MSurfType.C_X:
        cylinder = ((0.0, params[0], params[1]), (1.0, 0.0, 0.0), params[2])
    elif stype == MSurfType.CY:
        cylinder = ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), params[0])
    elif stype == MSurfType.C_Y:
        cylinder = ((params[0], 0.0, params[1]), (0.0, 1.0, 0.0), params[2])
    elif stype == MSurfType.CZ:
        cylinder = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), params[0])
    elif stype == MSurfType.C_Z:
        cylinder = ((params[0], params[1], 0.0), (0.0, 0.0, 1.0), params[2])
    elif stype == MSurfType.C_G and len(params) >= 7:
        cylinder = (tuple(params[0:3]), tuple(params[3:6]), params[6])
    if cylinder is not None:
        center, axis, radius = cylinder
        axis = _unit3(axis)
        e1, e2 = tangent_basis(axis)
        centre_projection = _dot3((cx - center[0], cy - center[1], cz - center[2]), axis)
        for i in range(count):
            angle = 2.0 * math.pi * (i + rng.random()) / max(1, count)
            axial = centre_projection + rng.uniform(-0.5 * diagonal, 0.5 * diagonal)
            radial = tuple(math.cos(angle) * e1[j] + math.sin(angle) * e2[j] for j in range(3))
            point = tuple(center[j] + axial * axis[j] + radius * radial[j] for j in range(3))
            add(point, radial)
        return pairs

    sphere = None
    if stype == MSurfType.SO:
        sphere = ((0.0, 0.0, 0.0), params[0])
    elif stype == MSurfType.SPH:
        sphere = (tuple(params[0:3]), params[3]) if len(params) >= 4 else ((0.0, 0.0, 0.0), params[0])
    if sphere is not None:
        center, radius = sphere
        golden = math.pi * (3.0 - math.sqrt(5.0))
        for i in range(count):
            z = 1.0 - 2.0 * (i + 0.5) / max(1, count)
            radial = math.sqrt(max(0.0, 1.0 - z * z))
            angle = golden * i
            normal = (radial * math.cos(angle), radial * math.sin(angle), z)
            point = tuple(center[j] + radius * normal[j] for j in range(3))
            add(point, normal)
        return pairs

    if stype in (MSurfType.TX, MSurfType.TY, MSurfType.TZ) and len(params) >= 6:
        center = tuple(params[0:3])
        major, axial_minor, radial_minor = params[3:6]
        for i in range(count):
            u = 2.0 * math.pi * (i + 0.5) / max(1, count)
            v = 2.0 * math.pi * ((i * 7) % max(1, count) + 0.5) / max(1, count)
            radial = major + radial_minor * math.cos(v)
            axial = axial_minor * math.sin(v)
            if stype == MSurfType.TX:
                point = (center[0] + axial, center[1] + radial * math.cos(u), center[2] + radial * math.sin(u))
                normal = (math.sin(v), math.cos(v) * math.cos(u), math.cos(v) * math.sin(u))
            elif stype == MSurfType.TY:
                point = (center[0] + radial * math.cos(u), center[1] + axial, center[2] + radial * math.sin(u))
                normal = (math.cos(v) * math.cos(u), math.sin(v), math.cos(v) * math.sin(u))
            else:
                point = (center[0] + radial * math.cos(u), center[1] + radial * math.sin(u), center[2] + axial)
                normal = (math.cos(v) * math.cos(u), math.cos(v) * math.sin(u), math.sin(v))
            add(point, normal)
        return pairs

    if stype == MSurfType.RPP and len(params) >= 6:
        x0, x1, y0, y1, z0, z1 = params[0:6]
        faces = [
            ((x0, None, None), (-1.0, 0.0, 0.0)), ((x1, None, None), (1.0, 0.0, 0.0)),
            ((None, y0, None), (0.0, -1.0, 0.0)), ((None, y1, None), (0.0, 1.0, 0.0)),
            ((None, None, z0), (0.0, 0.0, -1.0)), ((None, None, z1), (0.0, 0.0, 1.0)),
        ]
        for i in range(count):
            fixed, normal = faces[i % len(faces)]
            point = (
                fixed[0] if fixed[0] is not None else rng.uniform(min(x0, x1), max(x0, x1)),
                fixed[1] if fixed[1] is not None else rng.uniform(min(y0, y1), max(y0, y1)),
                fixed[2] if fixed[2] is not None else rng.uniform(min(z0, z1), max(z0, z1)),
            )
            add(point, normal)
        return pairs

    if stype == MSurfType.RCC and len(params) >= 7:
        base, height, radius = tuple(params[0:3]), tuple(params[3:6]), params[6]
        length = _norm3(height)
        if length <= 0.0:
            return pairs
        axis = _unit3(height)
        e1, e2 = tangent_basis(axis)
        for i in range(count):
            angle = 2.0 * math.pi * (i + rng.random()) / max(1, count)
            radial = tuple(math.cos(angle) * e1[j] + math.sin(angle) * e2[j] for j in range(3))
            if i % 4 == 0:
                rr = radius * math.sqrt(rng.random())
                point = tuple(base[j] + rr * radial[j] for j in range(3))
                add(point, tuple(-v for v in axis))
            elif i % 4 == 1:
                rr = radius * math.sqrt(rng.random())
                point = tuple(base[j] + height[j] + rr * radial[j] for j in range(3))
                add(point, axis)
            else:
                axial = rng.uniform(0.0, length)
                point = tuple(base[j] + axial * axis[j] + radius * radial[j] for j in range(3))
                add(point, radial)
        return pairs

    return pairs


def _run_validation(mcnp_model, cell_roots, cell_place, ctx, validate):
    samples = int(validate.get("samples", 0))
    local_samples = int(validate.get("local_samples", 0))
    boundary_samples = int(validate.get("boundary_samples", 0))
    if samples <= 0 and local_samples <= 0 and boundary_samples <= 0:
        return
    seed = int(validate.get("seed", 0))
    eps = float(validate.get("eps", 1e-6))
    cells_filter = validate.get("cells")
    out_path = validate.get("out_path")
    geant4_points_out = validate.get("geant4_points_out")

    bbox = ctx["bbox"]
    cx, cy, cz = bbox["cx"], bbox["cy"], bbox["cz"]
    hx, hy, hz = bbox["hx"], bbox["hy"], bbox["hz"]
    sx, sy, sz = bbox["shift"]

    rng = random.Random(seed)
    surface_map = ctx["surface_map"]
    cell_ast_map = {c.cell_id: c.geom_AST for c in mcnp_model.cells}
    tr_map = getattr(mcnp_model, "transforms", {})
    cell_trcl_map = {}
    for c in mcnp_model.cells:
        cell_trcl_map[c.cell_id] = _parse_transform_from_raw(getattr(c, "key_opts", {}).get("TRCL", ""), tr_map)
    eval_solids = ctx["eval_solids"]

    diagonal = 2.0 * math.sqrt(hx * hx + hy * hy + hz * hz)
    boundary_delta = float(validate.get("boundary_delta", max(10.0 * eps, diagonal * 1e-8)))
    report = {
        "schema_version": 2,
        "sampling": {
            "global_uniform_per_cell": samples,
            "cell_local_per_cell": local_samples,
            "boundary_pairs_per_surface": boundary_samples,
            "boundary_delta": boundary_delta,
        },
        "samples": samples,
        "seed": seed,
        "eps": eps,
        "cells": [],
        "totals": {
            "points": 0,
            "mismatches": 0,
            "boundary_pairs": 0,
            "active_boundary_pairs": 0,
            "boundary_surfaces_exercised": 0,
            "boundary_surfaces_skipped": 0,
        },
    }
    geant4_probe_rows = []

    def world_in_bbox(point):
        return (
            cx - hx <= point[0] <= cx + hx
            and cy - hy <= point[1] <= cy + hy
            and cz - hz <= point[2] <= cz + hz
        )

    for mcell in mcnp_model.cells:
        if cells_filter and mcell.cell_id not in cells_filter:
            continue
        root_name = cell_roots.get(mcell.cell_id)
        if root_name is None:
            continue
        eval_root = eval_solids.get(root_name)
        if eval_root is None:
            continue

        mismatches = []
        mismatch_count = 0
        trcl_pos, trcl_rot = _parse_transform_from_raw(getattr(mcell, "key_opts", {}).get("TRCL", ""), tr_map)

        def classify(p_world, strategy, surface_id=None, side=None):
            nonlocal mismatch_count
            p_mcnp_local = _apply_inverse_transform(p_world, trcl_pos, trcl_rot)
            in_mcnp = _eval_expr(mcell.geom_AST, p_mcnp_local, surface_map, cell_ast_map, eps, cell_trcl_map=cell_trcl_map)
            p_gdml = (p_world[0] + sx, p_world[1] + sy, p_world[2] + sz)
            pos, rot = cell_place.get(mcell.cell_id, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
            p_local = _apply_inverse_transform(p_gdml, pos, rot)
            in_gdml = eval_root.contains(p_local, eps)
            if geant4_points_out:
                geant4_probe_rows.append(
                    (root_name, p_local[0], p_local[1], p_local[2], int(in_mcnp), strategy, mcell.cell_id)
                )
            if in_mcnp != in_gdml:
                mismatch_count += 1
                if len(mismatches) < 5:
                    item = {
                        "p": [p_world[0], p_world[1], p_world[2]],
                        "mcnp": in_mcnp,
                        "gdml": in_gdml,
                        "strategy": strategy,
                    }
                    if surface_id is not None:
                        item["surface_id"] = surface_id
                    if side is not None:
                        item["side"] = side
                    mismatches.append(item)
            return in_mcnp, in_gdml

        strategy_counts = {"global_uniform": 0, "cell_local": 0, "boundary": 0}
        for _ in range(samples):
            p_world = (
                rng.uniform(cx - hx, cx + hx),
                rng.uniform(cy - hy, cy + hy),
                rng.uniform(cz - hz, cz + hz),
            )
            classify(p_world, "global_uniform")
            strategy_counts["global_uniform"] += 1

        cell_sampling_limits = []
        bounds = ctx.get("cell_bounds", {}).get(mcell.cell_id)
        shifts = (sx, sy, sz)
        globals_ = ((cx - hx, cx + hx), (cy - hy, cy + hy), (cz - hz, cz + hz))
        for index, axis in enumerate(("x", "y", "z")):
            pair = None if bounds is None else bounds.get(axis)
            if pair is None:
                cell_sampling_limits.append(globals_[index])
            else:
                cell_sampling_limits.append((pair[0] - shifts[index], pair[1] - shifts[index]))

        if local_samples > 0:
            for _ in range(local_samples):
                p_world = tuple(rng.uniform(*cell_sampling_limits[index]) for index in range(3))
                if world_in_bbox(p_world):
                    classify(p_world, "cell_local")
                    strategy_counts["cell_local"] += 1

        boundary_pairs = 0
        active_boundary_pairs = 0
        boundary_surfaces_exercised = 0
        boundary_surfaces_skipped = 0
        if boundary_samples > 0:
            local_bbox = dict(bbox)
            sampling_center = tuple(0.5 * (pair[0] + pair[1]) for pair in cell_sampling_limits)
            local_center = _apply_inverse_transform(sampling_center, trcl_pos, trcl_rot)
            local_bbox.update(
                {
                    "cx": local_center[0],
                    "cy": local_center[1],
                    "cz": local_center[2],
                    "hx": 0.5 * (cell_sampling_limits[0][1] - cell_sampling_limits[0][0]) + 2.0 * boundary_delta,
                    "hy": 0.5 * (cell_sampling_limits[1][1] - cell_sampling_limits[1][0]) + 2.0 * boundary_delta,
                    "hz": 0.5 * (cell_sampling_limits[2][1] - cell_sampling_limits[2][0]) + 2.0 * boundary_delta,
                }
            )
            resolve_surface = ctx.get("resolve_surface")
            for ref in _iter_surface_refs(mcell.geom_AST):
                surf = resolve_surface(ref.sid) if resolve_surface is not None else surface_map.get(ref.sid)
                if surf is None:
                    boundary_surfaces_skipped += 1
                    continue
                pairs = _surface_boundary_pairs(surf, local_bbox, boundary_samples, boundary_delta, rng)
                if not pairs:
                    boundary_surfaces_skipped += 1
                    continue
                boundary_surfaces_exercised += 1
                for minus_local, plus_local in pairs:
                    minus_world = _apply_transform(minus_local, trcl_pos, trcl_rot)
                    plus_world = _apply_transform(plus_local, trcl_pos, trcl_rot)
                    if not world_in_bbox(minus_world) or not world_in_bbox(plus_world):
                        continue
                    minus_result = classify(minus_world, "boundary", ref.sid, "minus")
                    plus_result = classify(plus_world, "boundary", ref.sid, "plus")
                    strategy_counts["boundary"] += 2
                    boundary_pairs += 1
                    if minus_result[0] != plus_result[0]:
                        active_boundary_pairs += 1

        total_points = sum(strategy_counts.values())
        ratio = mismatch_count / float(total_points) if total_points else 0.0
        cell_report = {
            "cell_id": mcell.cell_id,
            "points": total_points,
            "strategy_points": strategy_counts,
            "boundary_pairs": boundary_pairs,
            "active_boundary_pairs": active_boundary_pairs,
            "boundary_surfaces_exercised": boundary_surfaces_exercised,
            "boundary_surfaces_skipped": boundary_surfaces_skipped,
            "mismatches": mismatch_count,
            "ratio": ratio,
            "examples": mismatches,
        }
        report["cells"].append(cell_report)
        report["totals"]["points"] += total_points
        report["totals"]["mismatches"] += mismatch_count
        report["totals"]["boundary_pairs"] += boundary_pairs
        report["totals"]["active_boundary_pairs"] += active_boundary_pairs
        report["totals"]["boundary_surfaces_exercised"] += boundary_surfaces_exercised
        report["totals"]["boundary_surfaces_skipped"] += boundary_surfaces_skipped
        print(
            f"[validate] cell {mcell.cell_id}: mismatches {mismatch_count}/{total_points} ({ratio:.4%}); "
            f"active boundary pairs {active_boundary_pairs}/{boundary_pairs}"
        )

    if out_path:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"[validate] report written to {out_path}")
    if geant4_points_out:
        os.makedirs(os.path.dirname(geant4_points_out) or ".", exist_ok=True)
        with open(geant4_points_out, "w", encoding="utf-8") as f:
            f.write("solid\tx_cm\ty_cm\tz_cm\texpected_inside\tstrategy\tcell_id\n")
            for row in geant4_probe_rows:
                f.write("\t".join(str(value) for value in row) + "\n")
        print(f"[validate] Geant4 point-query file written to {geant4_points_out}")


def _parse_top_cells(val: str) -> List[int]:
    cells = []
    for part in val.split(','):
        part = part.strip()
        if part:
            cells.append(int(part))
    return cells


def _parse_bbox(val: str) -> Tuple[float, float, float, float, float, float]:
    parts = [p.strip() for p in val.split(',') if p.strip()]
    if len(parts) != 6:
        raise ValueError("--bbox expects 6 comma-separated values: x0,x1,y0,y1,z0,z1")
    return tuple(float(p) for p in parts)  # type: ignore


def _should_emit_terminal_cell(cell, has_material_cells: bool) -> bool:
    """Void is supplied by World unless an all-void deck needs visible geometry."""
    return cell.mat_id > 0 or not has_material_cells


def _compute_bbox(surfaces, margin: float, override=None):
    if override is not None:
        x0, x1, y0, y1, z0, z1 = override
    else:
        px_vals, py_vals, pz_vals = [], [], []
        sph_x, sph_y, sph_z = [], [], []
        rpp_x, rpp_y, rpp_z = [], [], []
        rad_max = 0.0
        plane_scale = 0.0
        for surf in surfaces:
            if surf.stype == MSurfType.PX:
                px_vals.append(surf.params[0])
            elif surf.stype == MSurfType.PY:
                py_vals.append(surf.params[0])
            elif surf.stype == MSurfType.PZ:
                pz_vals.append(surf.params[0])
            elif surf.stype == MSurfType.P and len(surf.params) >= 4:
                a, b, c, d = surf.params[:4]
                norm = math.sqrt(a * a + b * b + c * c)
                if norm > 1e-14:
                    plane_scale = max(plane_scale, abs(d) / norm)
            elif surf.stype in (MSurfType.SO, MSurfType.CX, MSurfType.CY, MSurfType.CZ):
                rad_max = max(rad_max, surf.params[0])
            elif surf.stype == MSurfType.C_X and len(surf.params) >= 3:
                y0s, z0s, r = surf.params[0:3]
                sph_y.extend([y0s - r, y0s + r])
                sph_z.extend([z0s - r, z0s + r])
            elif surf.stype == MSurfType.C_Y and len(surf.params) >= 3:
                x0s, z0s, r = surf.params[0:3]
                sph_x.extend([x0s - r, x0s + r])
                sph_z.extend([z0s - r, z0s + r])
            elif surf.stype == MSurfType.C_Z and len(surf.params) >= 3:
                x0s, y0s, r = surf.params[0:3]
                sph_x.extend([x0s - r, x0s + r])
                sph_y.extend([y0s - r, y0s + r])
            elif surf.stype == MSurfType.SPH:
                if len(surf.params) >= 4:
                    x0s, y0s, z0s, r = surf.params[0:4]
                elif len(surf.params) == 1:
                    x0s, y0s, z0s, r = 0.0, 0.0, 0.0, surf.params[0]
                else:
                    continue
                sph_x.extend([x0s - r, x0s + r])
                sph_y.extend([y0s - r, y0s + r])
                sph_z.extend([z0s - r, z0s + r])
            elif surf.stype == MSurfType.RPP and len(surf.params) >= 6:
                x0s, x1s, y0s, y1s, z0s, z1s = surf.params[0:6]
                rpp_x.extend([min(x0s, x1s), max(x0s, x1s)])
                rpp_y.extend([min(y0s, y1s), max(y0s, y1s)])
                rpp_z.extend([min(z0s, z1s), max(z0s, z1s)])
            elif surf.stype == MSurfType.BOX and len(surf.params) >= 12:
                x0s, y0s, z0s, *edges = surf.params[:12]
                a, b, c = edges[:3], edges[3:6], edges[6:9]
                vertices = [
                    (
                        x0s + ia * a[0] + ib * b[0] + ic * c[0],
                        y0s + ia * a[1] + ib * b[1] + ic * c[1],
                        z0s + ia * a[2] + ib * b[2] + ic * c[2],
                    )
                    for ia in (0, 1)
                    for ib in (0, 1)
                    for ic in (0, 1)
                ]
                rpp_x.extend(v[0] for v in vertices)
                rpp_y.extend(v[1] for v in vertices)
                rpp_z.extend(v[2] for v in vertices)
            elif surf.stype in (MSurfType.TX, MSurfType.TY, MSurfType.TZ) and len(surf.params) >= 6:
                x0s, y0s, z0s, major, minor1, minor2 = surf.params[:6]
                radial = abs(major) + max(abs(minor1), abs(minor2))
                axial = max(abs(minor1), abs(minor2))
                if surf.stype == MSurfType.TX:
                    spans = (axial, radial, radial)
                elif surf.stype == MSurfType.TY:
                    spans = (radial, axial, radial)
                else:
                    spans = (radial, radial, axial)
                sph_x.extend([x0s - spans[0], x0s + spans[0]])
                sph_y.extend([y0s - spans[1], y0s + spans[1]])
                sph_z.extend([z0s - spans[2], z0s + spans[2]])
            elif surf.stype == MSurfType.C_G and len(surf.params) >= 7:
                x0s, y0s, z0s, _ax, _ay, _az, radius = surf.params[:7]
                rad_max = max(rad_max, math.sqrt(x0s * x0s + y0s * y0s + z0s * z0s) + abs(radius))
            elif surf.stype == MSurfType.RCC and len(surf.params) >= 7:
                x0s, y0s, z0s, hx, hy, hz, r = surf.params[0:7]
                x1s, y1s, z1s = x0s + hx, y0s + hy, z0s + hz
                sph_x.extend([min(x0s, x1s) - r, max(x0s, x1s) + r])
                sph_y.extend([min(y0s, y1s) - r, max(y0s, y1s) + r])
                sph_z.extend([min(z0s, z1s) - r, max(z0s, z1s) + r])
            elif surf.stype == MSurfType.RHP and len(surf.params) >= 9:
                x0s, y0s, z0s, hx, hy, hz, ux, uy, uz = surf.params[0:9]
                axis, _, _ = _axis_aligned((hx, hy, hz))
                if axis == "x":
                    a = math.sqrt(uy * uy + uz * uz)
                    r = a / math.cos(math.pi / 6.0) if a > 0 else 0.0
                    sph_x.extend([min(x0s, x0s + hx), max(x0s, x0s + hx)])
                    sph_y.extend([y0s - r, y0s + r])
                    sph_z.extend([z0s - r, z0s + r])
                elif axis == "y":
                    a = math.sqrt(ux * ux + uz * uz)
                    r = a / math.cos(math.pi / 6.0) if a > 0 else 0.0
                    sph_x.extend([x0s - r, x0s + r])
                    sph_y.extend([min(y0s, y0s + hy), max(y0s, y0s + hy)])
                    sph_z.extend([z0s - r, z0s + r])
                else:
                    a = math.sqrt(ux * ux + uy * uy)
                    r = a / math.cos(math.pi / 6.0) if a > 0 else 0.0
                    sph_x.extend([x0s - r, x0s + r])
                    sph_y.extend([y0s - r, y0s + r])
                    sph_z.extend([min(z0s, z0s + hz), max(z0s, z0s + hz)])

        x_candidates = px_vals + sph_x + rpp_x
        y_candidates = py_vals + sph_y + rpp_y
        z_candidates = pz_vals + sph_z + rpp_z
        fallback_radius = max(rad_max, plane_scale)
        if fallback_radius > 0.0:
            # Origin-centred spheres/cylinders and general-plane scales must
            # enlarge, not merely replace, bounds inferred from axial planes.
            # Choosing only the plane extrema can otherwise make the Geant4
            # world smaller than an explicit graveyard sphere.
            x_candidates.extend([-fallback_radius, fallback_radius])
            y_candidates.extend([-fallback_radius, fallback_radius])
            z_candidates.extend([-fallback_radius, fallback_radius])

        if x_candidates:
            x0, x1 = min(x_candidates), max(x_candidates)
        elif fallback_radius > 0:
            x0, x1 = -fallback_radius, fallback_radius
        else:
            print("[warn] No X extents found; using default.")
            x0, x1 = -DEFAULT_HALF, DEFAULT_HALF

        if y_candidates:
            y0, y1 = min(y_candidates), max(y_candidates)
        elif fallback_radius > 0:
            y0, y1 = -fallback_radius, fallback_radius
        else:
            print("[warn] No Y extents found; using default.")
            y0, y1 = -DEFAULT_HALF, DEFAULT_HALF

        if z_candidates:
            z0, z1 = min(z_candidates), max(z_candidates)
        elif fallback_radius > 0:
            z0, z1 = -fallback_radius, fallback_radius
        else:
            print("[warn] No Z extents found; using default.")
            z0, z1 = -DEFAULT_HALF, DEFAULT_HALF

    if x0 == x1:
        x0 -= 1.0
        x1 += 1.0
    if y0 == y1:
        y0 -= 1.0
        y1 += 1.0
    if z0 == z1:
        z0 -= 1.0
        z1 += 1.0

    cx = 0.5 * (x0 + x1)
    cy = 0.5 * (y0 + y1)
    cz = 0.5 * (z0 + z1)

    hx = 0.5 * (x1 - x0) * (1.0 + margin)
    hy = 0.5 * (y1 - y0) * (1.0 + margin)
    hz = 0.5 * (z1 - z0) * (1.0 + margin)

    return {
        "cx": cx,
        "cy": cy,
        "cz": cz,
        "hx": hx,
        "hy": hy,
        "hz": hz,
        "shift": (-cx, -cy, -cz),
    }


def _make_vec(name: str, vtype: str, unit: str, xyz):
    return GVector(name, vtype, unit, x=xyz[0], y=xyz[1], z=xyz[2])


def _plane_halfspace(sid, axis, c, sense, ctx):
    bbox = ctx["bbox"]
    gdml_model = ctx["gdml"]
    bbox_name = ctx["bbox_name"]

    sx, sy, sz = bbox["shift"]
    if axis == "x":
        c = c + sx
        half = bbox["hx"]
        full_other = (2 * bbox["hy"], 2 * bbox["hz"])
        axis_index = 0
    elif axis == "y":
        c = c + sy
        half = bbox["hy"]
        full_other = (2 * bbox["hx"], 2 * bbox["hz"])
        axis_index = 1
    else:
        c = c + sz
        half = bbox["hz"]
        full_other = (2 * bbox["hx"], 2 * bbox["hy"])
        axis_index = 2

    keep_less = sense < 0
    if keep_less:
        cut_min = c
        cut_max = half
    else:
        cut_min = -half
        cut_max = c

    if cut_max <= cut_min:
        print(f"[warn] Plane half-space for surface {sid} is empty or full; using BBox.")
        return bbox_name

    cut_len = cut_max - cut_min
    center = 0.5 * (cut_min + cut_max)

    if axis_index == 0:
        xlen, ylen, zlen = cut_len, full_other[0], full_other[1]
        pos = (center, 0.0, 0.0)
    elif axis_index == 1:
        xlen, ylen, zlen = full_other[0], cut_len, full_other[1]
        pos = (0.0, center, 0.0)
    else:
        xlen, ylen, zlen = full_other[0], full_other[1], cut_len
        pos = (0.0, 0.0, center)

    cut_name = f"Cut_{axis.upper()}_{sid}_{'N' if sense < 0 else 'P'}"
    if cut_name not in ctx["solid_names"]:
        gdml_model.add_solid(GBox(cut_name, xlen, ylen, zlen))
        ctx["solid_names"].add(cut_name)
        ctx["eval_solids"][cut_name] = EvalBox(xlen, ylen, zlen)

    pos_vec = _make_vec(f"Pos_{cut_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{cut_name}", "rotation", "deg", (0.0, 0.0, 0.0))

    hs_name = f"HS_{axis.upper()}_{sid}_{'N' if sense < 0 else 'P'}"
    gsolid = GBooleanSolid(hs_name, "subtraction", bbox_name, cut_name, pos_vec, rot_vec)
    gdml_model.add_solid(gsolid)
    ctx["eval_solids"][hs_name] = EvalBoolean("subtraction", ctx["eval_solids"][bbox_name], ctx["eval_solids"][cut_name], pos, (0.0, 0.0, 0.0))
    return hs_name


def _general_plane_halfspace(surf, sense, ctx):
    """Clip the working bounding box by an arbitrarily oriented MCNP plane."""
    if len(surf.params) < 4:
        raise ValueError(f"Invalid P parameters for surface {surf.sid}: {surf.params}")
    a, b, c, d = surf.params[0:4]
    nlen = math.sqrt(a * a + b * b + c * c)
    if nlen <= 1e-15:
        raise ValueError(f"Degenerate P surface {surf.sid}: {surf.params}")

    nx, ny, nz = a / nlen, b / nlen, c / nlen
    bbox = ctx["bbox"]
    sx, sy, sz = bbox["shift"]
    # Coordinates written to GDML are shifted by bbox.shift.
    d_shifted = (d + a * sx + b * sy + c * sz) / nlen
    p0 = (nx * d_shifted, ny * d_shifted, nz * d_shifted)

    # Build an orthonormal frame whose local +Z axis is the plane normal.
    helper = (0.0, 0.0, 1.0) if abs(nz) < 0.9 else (1.0, 0.0, 0.0)
    e1 = _cross3(helper, (nx, ny, nz))
    e1n = _norm3(e1)
    e1 = (e1[0] / e1n, e1[1] / e1n, e1[2] / e1n)
    e2 = _cross3((nx, ny, nz), e1)
    matrix = [
        [e1[0], e2[0], nx],
        [e1[1], e2[1], ny],
        [e1[2], e2[2], nz],
    ]
    rot = _matrix_to_euler_deg_zyx(matrix)

    # The finite cutter must cover the part of the declared conversion domain
    # retained by this half-space.  A fixed depth measured from the plane is
    # not sufficient when users supply a domain far from a general P surface.
    # Work in the centred GDML frame, in which the bounding-box corners are
    # simply (+/-hx, +/-hy, +/-hz).
    corners = [
        (x, y, z)
        for x in (-bbox["hx"], bbox["hx"])
        for y in (-bbox["hy"], bbox["hy"])
        for z in (-bbox["hz"], bbox["hz"])
    ]
    signed = [
        (corner[0] - p0[0]) * nx
        + (corner[1] - p0[1]) * ny
        + (corner[2] - p0[2]) * nz
        for corner in corners
    ]
    diagonal = math.sqrt(bbox["hx"] ** 2 + bbox["hy"] ** 2 + bbox["hz"] ** 2)
    guard = max(1.0e-9, diagonal * 1.0e-9)

    # A signed surface reference keeps a*x+b*y+c*z-d <= 0 for sense < 0
    # and >= 0 for sense > 0.  If all corners are on the retained side, the
    # exact finite-domain result is the domain itself.  This avoids creating a
    # remote finite box that misses B entirely.
    if sense < 0 and max(signed) <= 0.0:
        return ctx["bbox_name"]
    if sense > 0 and min(signed) >= 0.0:
        return ctx["bbox_name"]

    if sense < 0:
        depth = max(-min(signed), guard)
    else:
        depth = max(max(signed), guard)

    transverse_half = max(
        max(abs(_dot3((corner[0] - p0[0], corner[1] - p0[1], corner[2] - p0[2]), axis)) for corner in corners)
        for axis in (e1, e2)
    ) + guard
    transverse = 2.0 * transverse_half
    direction = -1.0 if sense < 0 else 1.0
    pos = (
        p0[0] + direction * 0.5 * depth * nx,
        p0[1] + direction * 0.5 * depth * ny,
        p0[2] + direction * 0.5 * depth * nz,
    )

    cut_name = f"Cut_P_{surf.sid}_{'N' if sense < 0 else 'P'}"
    if cut_name not in ctx["solid_names"]:
        ctx["gdml"].add_solid(GBox(cut_name, transverse, transverse, depth))
        ctx["solid_names"].add(cut_name)
        ctx["eval_solids"][cut_name] = EvalBox(transverse, transverse, depth)

    pos_vec = _make_vec(f"Pos_{cut_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{cut_name}", "rotation", "deg", rot)
    hs_name = f"HS_P_{surf.sid}_{'N' if sense < 0 else 'P'}"
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, "intersection", ctx["bbox_name"], cut_name, pos_vec, rot_vec))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        "intersection", ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][cut_name], pos, rot
    )
    return hs_name


def _cylinder_halfspace(surf, sense, axis, ctx):
    bbox = ctx["bbox"]
    gdml_model = ctx["gdml"]
    bbox_name = ctx["bbox_name"]
    sx, sy, sz = bbox["shift"]

    if surf.stype == MSurfType.C_G and len(surf.params) >= 7:
        x0, y0, z0, ax, ay, az, rmax = surf.params[0:7]
        direction = _unit3((ax, ay, az))
        base = (x0 + sx, y0 + sy, z0 + sz)
        # Centre the finite GDML tube near the working bbox while keeping its
        # axis on the MCNP infinite-cylinder centreline.
        t = -_dot3(base, direction)
        pos = (base[0] + t * direction[0], base[1] + t * direction[1], base[2] + t * direction[2])
        diagonal = math.sqrt(bbox["hx"] ** 2 + bbox["hy"] ** 2 + bbox["hz"] ** 2)
        length = max(4.0 * diagonal, 1.0)
        rot = _rotation_from_z(direction)
        off = pos
    elif axis == "x" and surf.stype == MSurfType.C_X and len(surf.params) >= 3:
        cy0, cz0, rmax = surf.params[0:3]
        off = (0.0, cy0 + sy, cz0 + sz)
    elif axis == "y" and surf.stype == MSurfType.C_Y and len(surf.params) >= 3:
        cx0, cz0, rmax = surf.params[0:3]
        off = (cx0 + sx, 0.0, cz0 + sz)
    elif axis == "z" and surf.stype == MSurfType.C_Z and len(surf.params) >= 3:
        cx0, cy0, rmax = surf.params[0:3]
        off = (cx0 + sx, cy0 + sy, 0.0)
    else:
        rmax = surf.params[0]
        if axis == "x":
            off = (0.0, sy, sz)
        elif axis == "y":
            off = (sx, 0.0, sz)
        else:
            off = (sx, sy, 0.0)

    if surf.stype == MSurfType.C_G:
        pos = off
    elif axis == "x":
        length = 2 * bbox["hx"]
        rot = (0.0, 90.0, 0.0)
        pos = off
    elif axis == "y":
        length = 2 * bbox["hy"]
        rot = (-90.0, 0.0, 0.0)
        pos = off
    else:
        length = 2 * bbox["hz"]
        rot = (0.0, 0.0, 0.0)
        pos = off

    cyl_name = f"Cyl_{axis.upper()}_{surf.sid}"
    if cyl_name not in ctx["solid_names"]:
        gdml_model.add_solid(GTube(cyl_name, rmax, length))
        ctx["solid_names"].add(cyl_name)
        ctx["eval_solids"][cyl_name] = EvalTube(rmax, length)

    pos_vec = _make_vec(f"Pos_{cyl_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{cyl_name}", "rotation", "deg", rot)

    hs_name = f"HS_{axis.upper()}_{surf.sid}_{'N' if sense < 0 else 'P'}"
    btype = "intersection" if sense < 0 else "subtraction"
    gsolid = GBooleanSolid(hs_name, btype, bbox_name, cyl_name, pos_vec, rot_vec)
    gdml_model.add_solid(gsolid)
    ctx["eval_solids"][hs_name] = EvalBoolean(btype, ctx["eval_solids"][bbox_name], ctx["eval_solids"][cyl_name], pos, rot)
    return hs_name


def _sphere_halfspace(surf, sense, ctx):
    bbox = ctx["bbox"]
    gdml_model = ctx["gdml"]
    bbox_name = ctx["bbox_name"]
    sx, sy, sz = bbox["shift"]

    if surf.stype == MSurfType.SPH:
        if len(surf.params) >= 4:
            x0, y0, z0, rmax = surf.params[0:4]
        elif len(surf.params) == 1:
            x0, y0, z0, rmax = 0.0, 0.0, 0.0, surf.params[0]
        else:
            raise ValueError(f"Invalid SPH parameters for surface {surf.sid}: {surf.params}")
        pos = (x0 + sx, y0 + sy, z0 + sz)
    else:
        rmax = surf.params[0]
        pos = (sx, sy, sz)
    sph_name = f"Sph_{surf.sid}"
    if sph_name not in ctx["solid_names"]:
        gdml_model.add_solid(GSphere(sph_name, rmax))
        ctx["solid_names"].add(sph_name)
        ctx["eval_solids"][sph_name] = EvalSphere(rmax)

    pos_vec = _make_vec(f"Pos_{sph_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{sph_name}", "rotation", "deg", (0.0, 0.0, 0.0))

    hs_name = f"HS_SPH_{surf.sid}_{'N' if sense < 0 else 'P'}"
    btype = "intersection" if sense < 0 else "subtraction"
    gsolid = GBooleanSolid(hs_name, btype, bbox_name, sph_name, pos_vec, rot_vec)
    gdml_model.add_solid(gsolid)
    ctx["eval_solids"][hs_name] = EvalBoolean(
        btype, ctx["eval_solids"][bbox_name], ctx["eval_solids"][sph_name], pos, (0.0, 0.0, 0.0)
    )
    return hs_name


def _torus_halfspace(surf, sense, ctx):
    if len(surf.params) < 6:
        raise ValueError(f"Invalid torus parameters for surface {surf.sid}: {surf.params}")
    x0, y0, z0, major, axial_minor, radial_minor = surf.params[0:6]
    if not math.isclose(axial_minor, radial_minor, rel_tol=1e-9, abs_tol=1e-9):
        raise NotImplementedError(
            f"Elliptical torus surface {surf.sid} is not representable by the GDML torus solid: "
            f"axial={axial_minor}, radial={radial_minor}"
        )
    if major <= 0.0 or radial_minor <= 0.0:
        raise ValueError(f"Invalid torus radii for surface {surf.sid}: {surf.params}")

    bbox = ctx["bbox"]
    sx, sy, sz = bbox["shift"]
    pos = (x0 + sx, y0 + sy, z0 + sz)
    if surf.stype == MSurfType.TX:
        rot = (0.0, 90.0, 0.0)
    elif surf.stype == MSurfType.TY:
        rot = (-90.0, 0.0, 0.0)
    else:
        rot = (0.0, 0.0, 0.0)

    torus_name = f"Torus_{surf.sid}"
    if torus_name not in ctx["solid_names"]:
        if major > radial_minor:
            ctx["gdml"].add_solid(GTorus(torus_name, major, radial_minor))
        else:
            # G4Torus rejects horn/spindle tori (minor radius >= swept
            # radius), although MCNP permits them.  Represent the exact radial
            # interval at sampled z planes with a high-resolution generic
            # polycone.  With 720 circular intervals the maximum meridional
            # sagitta is below 3.5e-3 cm for the largest current corpus case.
            intervals = 720
            outer = []
            inner = []
            for i in range(intervals + 1):
                theta = -0.5 * math.pi + math.pi * i / intervals
                z = radial_minor * math.sin(theta)
                offset = radial_minor * math.cos(theta)
                outer.append((major + offset, z))
                inner.append((max(0.0, major - offset), z))
            rzpoints = outer + list(reversed(inner))
            ctx["gdml"].add_solid(GGenericPolycone(torus_name, rzpoints))
            print(
                f"[warn] Surface {surf.sid} is a horn/spindle torus; "
                f"approximated by a {intervals}-segment genericPolycone."
            )
        ctx["solid_names"].add(torus_name)
        ctx["eval_solids"][torus_name] = EvalTorus(major, radial_minor)

    pos_vec = _make_vec(f"Pos_{torus_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{torus_name}", "rotation", "deg", rot)
    hs_name = f"HS_Torus_{surf.sid}_{'N' if sense < 0 else 'P'}"
    op = "intersection" if sense < 0 else "subtraction"
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, op, ctx["bbox_name"], torus_name, pos_vec, rot_vec))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        op, ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][torus_name], pos, rot
    )
    return hs_name


def _sq_halfspace(surf, sense, ctx):
    if len(surf.params) < 10:
        raise ValueError(f"Invalid SQ parameters for surface {surf.sid}: {surf.params}")
    a, b, c, d, e, f, g, x0, y0, z0 = surf.params[0:10]
    if any(abs(value) > 1e-12 for value in (d, e, f)) or g >= 0.0:
        raise NotImplementedError(
            f"SQ surface {surf.sid} is not a centred axis-aligned elliptical cylinder"
        )
    zeros = [abs(value) <= 1e-12 for value in (a, b, c)]
    if sum(zeros) != 1 or any(value <= 0.0 for value, zero in zip((a, b, c), zeros) if not zero):
        raise NotImplementedError(
            f"SQ surface {surf.sid} is not a supported elliptical cylinder"
        )

    bbox = ctx["bbox"]
    sx, sy, sz = bbox["shift"]
    diagonal = math.sqrt(bbox["hx"] ** 2 + bbox["hy"] ** 2 + bbox["hz"] ** 2)
    dz = max(2.0 * diagonal, 0.5)
    if zeros[2]:
        dx, dy = math.sqrt(-g / a), math.sqrt(-g / b)
        pos, rot = (x0 + sx, y0 + sy, 0.0), (0.0, 0.0, 0.0)
    elif zeros[1]:
        dx, dy = math.sqrt(-g / a), math.sqrt(-g / c)
        pos, rot = (x0 + sx, 0.0, z0 + sz), (-90.0, 0.0, 0.0)
    else:
        dx, dy = math.sqrt(-g / b), math.sqrt(-g / c)
        pos, rot = (0.0, y0 + sy, z0 + sz), (0.0, 90.0, 0.0)

    name = f"SQEltube_{surf.sid}"
    if name not in ctx["solid_names"]:
        ctx["gdml"].add_solid(GEllipticalTube(name, dx, dy, dz))
        ctx["solid_names"].add(name)
        ctx["eval_solids"][name] = EvalEllipticalTube(dx, dy, dz)
    pos_vec = _make_vec(f"Pos_{name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rot)
    hs_name = f"HS_SQ_{surf.sid}_{'N' if sense < 0 else 'P'}"
    op = "intersection" if sense < 0 else "subtraction"
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, op, ctx["bbox_name"], name, pos_vec, rot_vec))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        op, ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][name], pos, rot
    )
    return hs_name


def _ellipsoid_halfspace(surf, sense, ctx):
    if len(surf.params) < 15:
        raise ValueError(f"Invalid ellipsoid parameters for surface {surf.sid}: {surf.params}")
    center = tuple(surf.params[0:3])
    e1, e2, e3 = (_unit3(tuple(surf.params[i:i+3])) for i in (3, 6, 9))
    ax, by, cz = surf.params[12:15]
    if min(ax, by, cz) <= 0.0:
        raise ValueError(f"Invalid ellipsoid radii for surface {surf.sid}: {surf.params}")
    if max(abs(_dot3(e1, e2)), abs(_dot3(e1, e3)), abs(_dot3(e2, e3))) > 1e-7:
        raise NotImplementedError(f"Ellipsoid surface {surf.sid} has non-orthogonal axes")
    matrix = [
        [e1[0], e2[0], e3[0]],
        [e1[1], e2[1], e3[1]],
        [e1[2], e2[2], e3[2]],
    ]
    rot = _matrix_to_euler_deg_zyx(matrix)
    sx, sy, sz = ctx["bbox"]["shift"]
    pos = (center[0] + sx, center[1] + sy, center[2] + sz)
    name = f"Ellipsoid_{surf.sid}"
    if name not in ctx["solid_names"]:
        ctx["gdml"].add_solid(GEllipsoid(name, ax, by, cz))
        ctx["solid_names"].add(name)
        ctx["eval_solids"][name] = EvalEllipsoid(ax, by, cz)
    pos_vec = _make_vec(f"Pos_{name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rot)
    hs_name = f"HS_ELL_{surf.sid}_{'N' if sense < 0 else 'P'}"
    op = "intersection" if sense < 0 else "subtraction"
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, op, ctx["bbox_name"], name, pos_vec, rot_vec))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        op, ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][name], pos, rot
    )
    return hs_name


def _ecyl_halfspace(surf, sense, ctx):
    if len(surf.params) < 14:
        raise ValueError(f"Invalid elliptical-cylinder parameters for surface {surf.sid}: {surf.params}")
    center = tuple(surf.params[0:3])
    e1 = _unit3(tuple(surf.params[3:6]))
    e2 = _unit3(tuple(surf.params[6:9]))
    axis = _unit3(tuple(surf.params[9:12]))
    r1, r2 = surf.params[12:14]
    if min(r1, r2) <= 0.0:
        raise ValueError(f"Invalid elliptical-cylinder radii for surface {surf.sid}: {surf.params}")
    if max(abs(_dot3(e1, e2)), abs(_dot3(e1, axis)), abs(_dot3(e2, axis))) > 1e-7:
        raise NotImplementedError(f"Elliptical cylinder {surf.sid} has non-orthogonal axes")
    matrix = [
        [e1[0], e2[0], axis[0]],
        [e1[1], e2[1], axis[1]],
        [e1[2], e2[2], axis[2]],
    ]
    rot = _matrix_to_euler_deg_zyx(matrix)
    bbox = ctx["bbox"]
    sx, sy, sz = bbox["shift"]
    shifted = (center[0] + sx, center[1] + sy, center[2] + sz)
    t = -_dot3(shifted, axis)
    pos = tuple(shifted[i] + t * axis[i] for i in range(3))
    diagonal = math.sqrt(bbox["hx"] ** 2 + bbox["hy"] ** 2 + bbox["hz"] ** 2)
    dz = max(2.0 * diagonal, 0.5)
    name = f"ECYL_{surf.sid}"
    if name not in ctx["solid_names"]:
        ctx["gdml"].add_solid(GEllipticalTube(name, r1, r2, dz))
        ctx["solid_names"].add(name)
        ctx["eval_solids"][name] = EvalEllipticalTube(r1, r2, dz)
    pos_vec = _make_vec(f"Pos_{name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rot)
    hs_name = f"HS_ECYL_{surf.sid}_{'N' if sense < 0 else 'P'}"
    op = "intersection" if sense < 0 else "subtraction"
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, op, ctx["bbox_name"], name, pos_vec, rot_vec))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        op, ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][name], pos, rot
    )
    return hs_name


def _cone_surface_parameters(surf):
    p = surf.params
    if surf.stype == MSurfType.CONE_G:
        if len(p) < 8:
            raise ValueError(f"Invalid general cone parameters for surface {surf.sid}: {p}")
        vertex = tuple(p[0:3])
        axis = _unit3(tuple(p[3:6]))
        t2 = p[6]
        sheet = int(round(p[7]))
    elif surf.stype == MSurfType.KX:
        if len(p) < 2:
            raise ValueError(f"Invalid KX parameters for surface {surf.sid}: {p}")
        vertex, axis, t2 = (p[0], 0.0, 0.0), (1.0, 0.0, 0.0), p[1]
        sheet = int(round(p[2])) if len(p) >= 3 else 0
    elif surf.stype == MSurfType.KY:
        if len(p) < 2:
            raise ValueError(f"Invalid KY parameters for surface {surf.sid}: {p}")
        vertex, axis, t2 = (0.0, p[0], 0.0), (0.0, 1.0, 0.0), p[1]
        sheet = int(round(p[2])) if len(p) >= 3 else 0
    elif surf.stype == MSurfType.KZ:
        if len(p) < 2:
            raise ValueError(f"Invalid KZ parameters for surface {surf.sid}: {p}")
        vertex, axis, t2 = (0.0, 0.0, p[0]), (0.0, 0.0, 1.0), p[1]
        sheet = int(round(p[2])) if len(p) >= 3 else 0
    elif surf.stype == MSurfType.K_X:
        if len(p) < 4:
            raise ValueError(f"Invalid K/X parameters for surface {surf.sid}: {p}")
        vertex, axis, t2 = (p[0], p[1], p[2]), (1.0, 0.0, 0.0), p[3]
        sheet = int(round(p[4])) if len(p) >= 5 else 0
    elif surf.stype == MSurfType.K_Y:
        if len(p) < 4:
            raise ValueError(f"Invalid K/Y parameters for surface {surf.sid}: {p}")
        vertex, axis, t2 = (p[0], p[1], p[2]), (0.0, 1.0, 0.0), p[3]
        sheet = int(round(p[4])) if len(p) >= 5 else 0
    elif surf.stype == MSurfType.K_Z:
        if len(p) < 4:
            raise ValueError(f"Invalid K/Z parameters for surface {surf.sid}: {p}")
        vertex, axis, t2 = (p[0], p[1], p[2]), (0.0, 0.0, 1.0), p[3]
        sheet = int(round(p[4])) if len(p) >= 5 else 0
    else:
        raise ValueError(f"Not a cone surface: {surf.stype}")
    if t2 <= 0.0 or sheet not in (-1, 0, 1):
        raise ValueError(f"Invalid cone parameters for surface {surf.sid}: {p}")
    return vertex, axis, t2, sheet


def _symmetric_eigen_3x3(matrix):
    """Jacobi eigensolver for a real symmetric 3x3 matrix."""
    a = [list(map(float, row)) for row in matrix]
    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(60):
        pairs = ((0, 1), (0, 2), (1, 2))
        p, q = max(pairs, key=lambda ij: abs(a[ij[0]][ij[1]]))
        if abs(a[p][q]) <= 1e-14 * max(1.0, max(abs(a[i][i]) for i in range(3))):
            break
        phi = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        c, s = math.cos(phi), math.sin(phi)
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = c*c*app - 2*s*c*apq + s*s*aqq
        a[q][q] = s*s*app + 2*s*c*apq + c*c*aqq
        a[p][q] = a[q][p] = 0.0
        for r in range(3):
            if r in (p, q):
                continue
            arp, arq = a[r][p], a[r][q]
            a[r][p] = a[p][r] = c*arp - s*arq
            a[r][q] = a[q][r] = s*arp + c*arq
        for r in range(3):
            vrp, vrq = v[r][p], v[r][q]
            v[r][p] = c*vrp - s*vrq
            v[r][q] = s*vrp + c*vrq
    pairs = sorted((a[i][i], (v[0][i], v[1][i], v[2][i])) for i in range(3))
    return [item[0] for item in pairs], [_unit3(item[1]) for item in pairs]


def _canonicalize_gq(surf):
    if len(surf.params) < 10:
        raise ValueError(f"Invalid GQ parameters for surface {surf.sid}: {surf.params}")
    a, b, c, d, e, f, g, h, j, k = surf.params[0:10]
    q = [[a, d/2.0, f/2.0], [d/2.0, b, e/2.0], [f/2.0, e/2.0, c]]
    linear = (g, h, j)
    eigenvalues, axes = _symmetric_eigen_3x3(q)
    scale = max(1.0, *(abs(value) for value in eigenvalues))
    tol = 1e-7 * scale
    active = [index for index, value in enumerate(eigenvalues) if abs(value) > tol]
    null = [index for index in range(3) if index not in active]
    projected_linear = [_dot3(linear, axis) for axis in axes]
    center_coords = [0.0, 0.0, 0.0]
    for index in active:
        center_coords[index] = -projected_linear[index] / (2.0 * eigenvalues[index])
    center = tuple(sum(center_coords[i] * axes[i][component] for i in range(3)) for component in range(3))
    qc = _mat_vec_mul(q, center)
    shifted_k = k + _dot3(linear, center) + _dot3(center, qc)

    if len(active) == 2 and len(null) == 1:
        null_linear = abs(projected_linear[null[0]])
        if null_linear > 1e-6 * max(1.0, _norm3(linear)):
            raise NotImplementedError(f"Parabolic GQ surface {surf.sid} is not supported")
        if shifted_k >= 0.0 or any(eigenvalues[index] <= tol for index in active):
            raise NotImplementedError(f"Non-elliptic GQ cylinder {surf.sid} is not supported")
        e1, e2 = axes[active[0]], axes[active[1]]
        axis = axes[null[0]]
        if _dot3(_cross3(e1, e2), axis) < 0.0:
            axis = tuple(-value for value in axis)
        r1 = math.sqrt(-shifted_k / eigenvalues[active[0]])
        r2 = math.sqrt(-shifted_k / eigenvalues[active[1]])
        return MSurface(surf.sid, MSurfType.ECYL_G, [*center, *e1, *e2, *axis, r1, r2])

    if len(active) == 3 and all(value > tol for value in eigenvalues) and shifted_k < 0.0:
        e1, e2, e3 = axes
        if _dot3(_cross3(e1, e2), e3) < 0.0:
            e3 = tuple(-value for value in e3)
        radii = [math.sqrt(-shifted_k / value) for value in eigenvalues]
        return MSurface(surf.sid, MSurfType.ELL_G, [*center, *e1, *e2, *e3, *radii])

    positive = [index for index, value in enumerate(eigenvalues) if value > tol]
    negative = [index for index, value in enumerate(eigenvalues) if value < -tol]
    k_scale = max(1.0, abs(k), abs(shifted_k), _norm3(linear), scale)
    if len(positive) == 2 and len(negative) == 1 and abs(shifted_k) <= 1e-6 * k_scale:
        p1, p2, neg = positive[0], positive[1], negative[0]
        if not math.isclose(eigenvalues[p1], eigenvalues[p2], rel_tol=1e-6, abs_tol=tol):
            raise NotImplementedError(f"Elliptical GQ cone {surf.sid} is not supported by GDML cone")
        t2 = -eigenvalues[neg] / (0.5 * (eigenvalues[p1] + eigenvalues[p2]))
        return MSurface(surf.sid, MSurfType.CONE_G, [*center, *axes[neg], t2, 0.0])

    raise NotImplementedError(f"GQ surface {surf.sid} is not a supported ellipsoid, elliptic cylinder, or circular cone")


def _gq_halfspace(surf, sense, ctx):
    canonical = _canonicalize_gq(surf)
    if canonical.stype == MSurfType.ECYL_G:
        return _ecyl_halfspace(canonical, sense, ctx)
    if canonical.stype == MSurfType.ELL_G:
        return _ellipsoid_halfspace(canonical, sense, ctx)
    if canonical.stype == MSurfType.CONE_G:
        return _cone_halfspace(canonical, sense, ctx)
    raise ValueError(f"Unexpected canonical GQ type {canonical.stype}")


def _cone_halfspace(surf, sense, ctx):
    vertex, axis, t2, sheet = _cone_surface_parameters(surf)
    bbox = ctx["bbox"]
    sx, sy, sz = bbox["shift"]
    shifted_vertex = (vertex[0] + sx, vertex[1] + sy, vertex[2] + sz)
    diagonal = math.sqrt(bbox["hx"] ** 2 + bbox["hy"] ** 2 + bbox["hz"] ** 2)
    length = max(4.0 * diagonal, 1.0)
    outer_radius = math.sqrt(t2) * length

    sheet_names = []
    directions = ([1] if sheet > 0 else [-1] if sheet < 0 else [1, -1])
    for direction_sign in directions:
        direction = tuple(direction_sign * component for component in axis)
        rot = _rotation_from_z(direction)
        pos = tuple(shifted_vertex[i] + 0.5 * length * direction[i] for i in range(3))
        cone_name = f"Cone_{surf.sid}_{'P' if direction_sign > 0 else 'N'}"
        if cone_name not in ctx["solid_names"]:
            ctx["gdml"].add_solid(GCons(cone_name, 0.0, outer_radius, length))
            ctx["solid_names"].add(cone_name)
            ctx["eval_solids"][cone_name] = EvalCons(0.0, outer_radius, length)
        pos_vec = _make_vec(f"Pos_{cone_name}", "position", "cm", pos)
        rot_vec = _make_vec(f"Rot_{cone_name}", "rotation", "deg", rot)
        clipped = f"ConeClip_{surf.sid}_{'P' if direction_sign > 0 else 'N'}"
        if clipped not in ctx["solid_names"]:
            ctx["gdml"].add_solid(
                GBooleanSolid(clipped, "intersection", ctx["bbox_name"], cone_name, pos_vec, rot_vec)
            )
            ctx["solid_names"].add(clipped)
            ctx["eval_solids"][clipped] = EvalBoolean(
                "intersection", ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][cone_name], pos, rot
            )
        sheet_names.append(clipped)

    cone_region = sheet_names[0]
    if len(sheet_names) == 2:
        cone_region = f"ConeUnion_{surf.sid}"
        if cone_region not in ctx["solid_names"]:
            zero_pos = _make_vec(f"Pos_{cone_region}", "position", "cm", (0.0, 0.0, 0.0))
            zero_rot = _make_vec(f"Rot_{cone_region}", "rotation", "deg", (0.0, 0.0, 0.0))
            ctx["gdml"].add_solid(GBooleanSolid(cone_region, "union", sheet_names[0], sheet_names[1], zero_pos, zero_rot))
            ctx["solid_names"].add(cone_region)
            ctx["eval_solids"][cone_region] = EvalBoolean(
                "union", ctx["eval_solids"][sheet_names[0]], ctx["eval_solids"][sheet_names[1]],
                (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
            )

    if sense < 0:
        return cone_region
    hs_name = f"HS_Cone_{surf.sid}_P"
    zero_pos = _make_vec(f"Pos_{hs_name}", "position", "cm", (0.0, 0.0, 0.0))
    zero_rot = _make_vec(f"Rot_{hs_name}", "rotation", "deg", (0.0, 0.0, 0.0))
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, "subtraction", ctx["bbox_name"], cone_region, zero_pos, zero_rot))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        "subtraction", ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][cone_region],
        (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    )
    return hs_name


def _rpp_halfspace(surf, sense, ctx):
    bbox = ctx["bbox"]
    gdml_model = ctx["gdml"]
    bbox_name = ctx["bbox_name"]
    sx, sy, sz = bbox["shift"]

    x0, x1, y0, y1, z0, z1 = surf.params[0:6]
    xmin, xmax = min(x0, x1) + sx, max(x0, x1) + sx
    ymin, ymax = min(y0, y1) + sy, max(y0, y1) + sy
    zmin, zmax = min(z0, z1) + sz, max(z0, z1) + sz

    xlen, ylen, zlen = xmax - xmin, ymax - ymin, zmax - zmin
    pos = (0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax))

    box_name = f"RPP_{surf.sid}"
    if box_name not in ctx["solid_names"]:
        gdml_model.add_solid(GBox(box_name, xlen, ylen, zlen))
        ctx["solid_names"].add(box_name)
        ctx["eval_solids"][box_name] = EvalBox(xlen, ylen, zlen)

    pos_vec = _make_vec(f"Pos_{box_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{box_name}", "rotation", "deg", (0.0, 0.0, 0.0))

    hs_name = f"HS_RPP_{surf.sid}_{'N' if sense < 0 else 'P'}"
    btype = "intersection" if sense < 0 else "subtraction"
    gsolid = GBooleanSolid(hs_name, btype, bbox_name, box_name, pos_vec, rot_vec)
    gdml_model.add_solid(gsolid)
    ctx["eval_solids"][hs_name] = EvalBoolean(
        btype, ctx["eval_solids"][bbox_name], ctx["eval_solids"][box_name], pos, (0.0, 0.0, 0.0)
    )
    return hs_name


def _box_halfspace(surf, sense, ctx):
    if len(surf.params) < 12:
        raise ValueError(f"Invalid BOX parameters for surface {surf.sid}: {surf.params}")
    bbox = ctx["bbox"]
    sx, sy, sz = bbox["shift"]
    x0, y0, z0, *rest = surf.params[0:12]
    a, b, c = tuple(rest[0:3]), tuple(rest[3:6]), tuple(rest[6:9])
    lengths = (_norm3(a), _norm3(b), _norm3(c))
    if min(lengths) <= 1e-12:
        raise ValueError(f"Degenerate BOX surface {surf.sid}: {surf.params}")
    e1 = _unit3(a)
    e2 = _unit3(b)
    e3 = _unit3(c)
    if max(abs(_dot3(e1, e2)), abs(_dot3(e1, e3)), abs(_dot3(e2, e3))) > 1e-7:
        raise NotImplementedError(f"Skew BOX surface {surf.sid} cannot be represented as a GDML box")
    matrix = [
        [e1[0], e2[0], e3[0]],
        [e1[1], e2[1], e3[1]],
        [e1[2], e2[2], e3[2]],
    ]
    rot = _matrix_to_euler_deg_zyx(matrix)
    pos = (
        x0 + 0.5 * (a[0] + b[0] + c[0]) + sx,
        y0 + 0.5 * (a[1] + b[1] + c[1]) + sy,
        z0 + 0.5 * (a[2] + b[2] + c[2]) + sz,
    )
    name = f"BOX_{surf.sid}"
    if name not in ctx["solid_names"]:
        ctx["gdml"].add_solid(GBox(name, *lengths))
        ctx["solid_names"].add(name)
        ctx["eval_solids"][name] = EvalBox(*lengths)
    pos_vec = _make_vec(f"Pos_{name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rot)
    hs_name = f"HS_BOX_{surf.sid}_{'N' if sense < 0 else 'P'}"
    op = "intersection" if sense < 0 else "subtraction"
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, op, ctx["bbox_name"], name, pos_vec, rot_vec))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        op, ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][name], pos, rot
    )
    return hs_name


def _rcc_halfspace(surf, sense, ctx):
    bbox = ctx["bbox"]
    gdml_model = ctx["gdml"]
    bbox_name = ctx["bbox_name"]
    sx, sy, sz = bbox["shift"]

    x0, y0, z0, hx, hy, hz, rmax = surf.params[0:7]
    length = _norm3((hx, hy, hz))
    if length <= 0.0:
        raise ValueError(f"RCC surface {surf.sid} has a zero-length axis")
    rot = _rotation_from_z((hx, hy, hz))
    pos = (x0 + 0.5 * hx + sx, y0 + 0.5 * hy + sy, z0 + 0.5 * hz + sz)

    cyl_name = f"RCC_{surf.sid}"
    if cyl_name not in ctx["solid_names"]:
        gdml_model.add_solid(GTube(cyl_name, rmax, length))
        ctx["solid_names"].add(cyl_name)
        ctx["eval_solids"][cyl_name] = EvalTube(rmax, length)

    pos_vec = _make_vec(f"Pos_{cyl_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{cyl_name}", "rotation", "deg", rot)
    hs_name = f"HS_RCC_{surf.sid}_{'N' if sense < 0 else 'P'}"
    btype = "intersection" if sense < 0 else "subtraction"
    gsolid = GBooleanSolid(hs_name, btype, bbox_name, cyl_name, pos_vec, rot_vec)
    gdml_model.add_solid(gsolid)
    ctx["eval_solids"][hs_name] = EvalBoolean(btype, ctx["eval_solids"][bbox_name], ctx["eval_solids"][cyl_name], pos, rot)
    return hs_name


def _trc_halfspace(surf, sense, ctx):
    if len(surf.params) < 8:
        raise ValueError(f"Invalid TRC parameters for surface {surf.sid}: {surf.params}")
    x0, y0, z0, hx, hy, hz, r1, r2 = surf.params[0:8]
    length = _norm3((hx, hy, hz))
    if length <= 0.0 or min(r1, r2) < 0.0:
        raise ValueError(f"Invalid TRC geometry for surface {surf.sid}: {surf.params}")
    rot = _rotation_from_z((hx, hy, hz))
    sx, sy, sz = ctx["bbox"]["shift"]
    pos = (x0 + 0.5 * hx + sx, y0 + 0.5 * hy + sy, z0 + 0.5 * hz + sz)
    name = f"TRC_{surf.sid}"
    if name not in ctx["solid_names"]:
        ctx["gdml"].add_solid(GCons(name, r1, r2, length))
        ctx["solid_names"].add(name)
        ctx["eval_solids"][name] = EvalCons(r1, r2, length)
    pos_vec = _make_vec(f"Pos_{name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rot)
    hs_name = f"HS_TRC_{surf.sid}_{'N' if sense < 0 else 'P'}"
    op = "intersection" if sense < 0 else "subtraction"
    ctx["gdml"].add_solid(GBooleanSolid(hs_name, op, ctx["bbox_name"], name, pos_vec, rot_vec))
    ctx["eval_solids"][hs_name] = EvalBoolean(
        op, ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][name], pos, rot
    )
    return hs_name


def _rhp_halfspace(surf, sense, ctx):
    bbox = ctx["bbox"]
    gdml_model = ctx["gdml"]
    bbox_name = ctx["bbox_name"]
    sx, sy, sz = bbox["shift"]

    x0, y0, z0, hx, hy, hz, ux, uy, uz = surf.params[0:9]
    axis, length, _ = _axis_aligned((hx, hy, hz))
    if axis is None or length <= 0.0:
        print(f"[warn] RHP surface {surf.sid} is not axis-aligned; fallback to BBox clipping.")
        return bbox_name

    if axis == "x":
        a = math.sqrt(uy * uy + uz * uz)
        rot = (0.0, 90.0, 0.0)
    elif axis == "y":
        a = math.sqrt(ux * ux + uz * uz)
        rot = (-90.0, 0.0, 0.0)
    else:
        a = math.sqrt(ux * ux + uy * uy)
        rot = (0.0, 0.0, 0.0)
    if a <= 0.0:
        print(f"[warn] RHP surface {surf.sid} has invalid apothem; fallback to BBox clipping.")
        return bbox_name

    # GDML polyhedra use the radius to the outer side of each regular sector.
    # MCNP's RHP transverse vector carries that same apothem magnitude.
    rmax = a
    face_phi = _hex_face_angle_deg(axis, (ux, uy, uz))
    startphi = face_phi - 30.0
    pos = (x0 + 0.5 * hx + sx, y0 + 0.5 * hy + sy, z0 + 0.5 * hz + sz)

    poly_name = f"RHP_{surf.sid}"
    if poly_name not in ctx["solid_names"]:
        zplanes = [(-0.5 * length, 0.0, rmax), (0.5 * length, 0.0, rmax)]
        gdml_model.add_solid(GPolyhedra(poly_name, 6, zplanes, startphi=startphi, deltaphi=360.0))
        ctx["solid_names"].add(poly_name)
        ctx["eval_solids"][poly_name] = EvalHexPrism(rmax, length, startphi)

    pos_vec = _make_vec(f"Pos_{poly_name}", "position", "cm", pos)
    rot_vec = _make_vec(f"Rot_{poly_name}", "rotation", "deg", rot)
    hs_name = f"HS_RHP_{surf.sid}_{'N' if sense < 0 else 'P'}"
    btype = "intersection" if sense < 0 else "subtraction"
    gsolid = GBooleanSolid(hs_name, btype, bbox_name, poly_name, pos_vec, rot_vec)
    gdml_model.add_solid(gsolid)
    ctx["eval_solids"][hs_name] = EvalBoolean(
        btype, ctx["eval_solids"][bbox_name], ctx["eval_solids"][poly_name], pos, rot
    )
    return hs_name


def _solid_from_surface(surf, sense, ctx):
    key = (surf.sid, sense)
    if key in ctx["halfspace_cache"]:
        return ctx["halfspace_cache"][key]

    if surf.stype == MSurfType.P:
        name = _general_plane_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.PX:
        name = _plane_halfspace(surf.sid, "x", surf.params[0], sense, ctx)
    elif surf.stype == MSurfType.PY:
        name = _plane_halfspace(surf.sid, "y", surf.params[0], sense, ctx)
    elif surf.stype == MSurfType.PZ:
        name = _plane_halfspace(surf.sid, "z", surf.params[0], sense, ctx)
    elif surf.stype == MSurfType.CX:
        name = _cylinder_halfspace(surf, sense, "x", ctx)
    elif surf.stype == MSurfType.C_X:
        name = _cylinder_halfspace(surf, sense, "x", ctx)
    elif surf.stype == MSurfType.CY:
        name = _cylinder_halfspace(surf, sense, "y", ctx)
    elif surf.stype == MSurfType.C_Y:
        name = _cylinder_halfspace(surf, sense, "y", ctx)
    elif surf.stype == MSurfType.CZ:
        name = _cylinder_halfspace(surf, sense, "z", ctx)
    elif surf.stype == MSurfType.C_Z:
        name = _cylinder_halfspace(surf, sense, "z", ctx)
    elif surf.stype == MSurfType.C_G:
        name = _cylinder_halfspace(surf, sense, "general", ctx)
    elif surf.stype == MSurfType.SO:
        name = _sphere_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.SPH:
        name = _sphere_halfspace(surf, sense, ctx)
    elif surf.stype in (MSurfType.TX, MSurfType.TY, MSurfType.TZ):
        name = _torus_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.SQ:
        name = _sq_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.ELL_G:
        name = _ellipsoid_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.ECYL_G:
        name = _ecyl_halfspace(surf, sense, ctx)
    elif surf.stype in (
        MSurfType.KX, MSurfType.KY, MSurfType.KZ,
        MSurfType.K_X, MSurfType.K_Y, MSurfType.K_Z,
    ):
        name = _cone_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.GQ:
        name = _gq_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.CONE_G:
        name = _cone_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.RPP:
        name = _rpp_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.BOX:
        name = _box_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.RCC:
        name = _rcc_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.TRC:
        name = _trc_halfspace(surf, sense, ctx)
    elif surf.stype == MSurfType.RHP:
        name = _rhp_halfspace(surf, sense, ctx)
    else:
        raise ValueError(f"Unsupported surface type: {surf.stype}")

    ctx["halfspace_cache"][key] = name
    return name


def _extract_intersection_surfaces(node):
    if isinstance(node, SurfaceRef):
        return [node]
    if isinstance(node, IntersectionNode):
        left = _extract_intersection_surfaces(node.left)
        right = _extract_intersection_surfaces(node.right)
        if left is None or right is None:
            return None
        return left + right
    return None


def _is_zero_transform(pos, rot, eps=1e-9):
    return all(abs(v) < eps for v in pos) and all(abs(v) < eps for v in rot)

def _round_key(val: float, ndigits: int = 6) -> float:
    if abs(val) < 1e-12:
        return 0.0
    return round(float(val), ndigits)


def _try_build_primitive(node, cell_id, ctx):
    surf_refs = _extract_intersection_surfaces(node)
    if surf_refs is None:
        return None

    resolve_surface = ctx.get("resolve_surface")
    bbox = ctx["bbox"]
    sx, sy, sz = bbox["shift"]

    surfaces = []
    for ref in surf_refs:
        surf = resolve_surface(ref.sid) if resolve_surface is not None else ctx["surface_map"].get(ref.sid)
        if surf is None:
            raise ValueError(f"Surface {ref.sid} not found in model")
        surfaces.append((ref, surf))

    types = [s.stype for _, s in surfaces]
    unique_types = set(types)

    # RPP recognition: a single inside RPP can be represented as a box primitive.
    if unique_types == {MSurfType.RPP} and len(surfaces) == 1:
        ref, surf = surfaces[0]
        if ref.sense < 0 and len(surf.params) >= 6:
            x0, x1, y0, y1, z0, z1 = surf.params[0:6]
            xmin, xmax = min(x0, x1) + sx, max(x0, x1) + sx
            ymin, ymax = min(y0, y1) + sy, max(y0, y1) + sy
            zmin, zmax = min(z0, z1) + sz, max(z0, z1) + sz
            xlen, ylen, zlen = xmax - xmin, ymax - ymin, zmax - zmin
            cx, cy, cz = 0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax)
            key = ("box", _round_key(xlen), _round_key(ylen), _round_key(zlen))
            name = ctx["prim_cache"].get(key)
            if name is None:
                idx = ctx["prim_counter"]
                ctx["prim_counter"] += 1
                name = f"PrimBox_{idx}"
                ctx["gdml"].add_solid(GBox(name, xlen, ylen, zlen))
                ctx["solid_names"].add(name)
                ctx["eval_solids"][name] = EvalBox(xlen, ylen, zlen)
                ctx["prim_cache"][key] = name
            return name, (cx, cy, cz), (0.0, 0.0, 0.0), "box"

    # Box recognition: only PX/PY/PZ planes
    if unique_types.issubset({MSurfType.PX, MSurfType.PY, MSurfType.PZ}):
        x_min, x_max = -float("inf"), float("inf")
        y_min, y_max = -float("inf"), float("inf")
        z_min, z_max = -float("inf"), float("inf")
        for ref, surf in surfaces:
            if surf.stype == MSurfType.PX:
                c = surf.params[0] + sx
                if ref.sense < 0:
                    x_max = min(x_max, c)
                else:
                    x_min = max(x_min, c)
            elif surf.stype == MSurfType.PY:
                c = surf.params[0] + sy
                if ref.sense < 0:
                    y_max = min(y_max, c)
                else:
                    y_min = max(y_min, c)
            elif surf.stype == MSurfType.PZ:
                c = surf.params[0] + sz
                if ref.sense < 0:
                    z_max = min(z_max, c)
                else:
                    z_min = max(z_min, c)

        if all(v != float("inf") and v != -float("inf") for v in [x_min, x_max, y_min, y_max, z_min, z_max]) and \
           x_min < x_max and y_min < y_max and z_min < z_max:
            xlen = x_max - x_min
            ylen = y_max - y_min
            zlen = z_max - z_min
            cx = 0.5 * (x_min + x_max)
            cy = 0.5 * (y_min + y_max)
            cz = 0.5 * (z_min + z_max)
            key = ("box", _round_key(xlen), _round_key(ylen), _round_key(zlen))
            name = ctx["prim_cache"].get(key)
            if name is None:
                idx = ctx["prim_counter"]
                ctx["prim_counter"] += 1
                name = f"PrimBox_{idx}"
                ctx["gdml"].add_solid(GBox(name, xlen, ylen, zlen))
                ctx["solid_names"].add(name)
                ctx["eval_solids"][name] = EvalBox(xlen, ylen, zlen)
                ctx["prim_cache"][key] = name
            return name, (cx, cy, cz), (0.0, 0.0, 0.0), "box"

    # Cylinder recognition: one axis, plus two planes along axis
    cyl_axes = [t for t in unique_types if t in (MSurfType.CX, MSurfType.CY, MSurfType.CZ)]
    if len(cyl_axes) == 1 and unique_types.issubset({MSurfType.CX, MSurfType.CY, MSurfType.CZ, MSurfType.PX, MSurfType.PY, MSurfType.PZ}):
        axis = cyl_axes[0]
        # reject if planes not aligned with cylinder axis
        if axis == MSurfType.CX and any(t not in (MSurfType.CX, MSurfType.PX) for t in unique_types):
            return None
        if axis == MSurfType.CY and any(t not in (MSurfType.CY, MSurfType.PY) for t in unique_types):
            return None
        if axis == MSurfType.CZ and any(t not in (MSurfType.CZ, MSurfType.PZ) for t in unique_types):
            return None

        # bounds along axis
        if axis == MSurfType.CX:
            lo, hi = -float("inf"), float("inf")
            for ref, surf in surfaces:
                if surf.stype == MSurfType.PX:
                    c = surf.params[0] + sx
                    if ref.sense < 0:
                        hi = min(hi, c)
                    else:
                        lo = max(lo, c)
            if lo == -float("inf") or hi == float("inf") or lo >= hi:
                return None
            length = hi - lo
            center = (0.5 * (lo + hi), sy, sz)
            rot = (0.0, 90.0, 0.0)
        elif axis == MSurfType.CY:
            lo, hi = -float("inf"), float("inf")
            for ref, surf in surfaces:
                if surf.stype == MSurfType.PY:
                    c = surf.params[0] + sy
                    if ref.sense < 0:
                        hi = min(hi, c)
                    else:
                        lo = max(lo, c)
            if lo == -float("inf") or hi == float("inf") or lo >= hi:
                return None
            length = hi - lo
            center = (sx, 0.5 * (lo + hi), sz)
            rot = (-90.0, 0.0, 0.0)
        else:
            lo, hi = -float("inf"), float("inf")
            for ref, surf in surfaces:
                if surf.stype == MSurfType.PZ:
                    c = surf.params[0] + sz
                    if ref.sense < 0:
                        hi = min(hi, c)
                    else:
                        lo = max(lo, c)
            if lo == -float("inf") or hi == float("inf") or lo >= hi:
                return None
            length = hi - lo
            center = (sx, sy, 0.5 * (lo + hi))
            rot = (0.0, 0.0, 0.0)

        # radii
        cyl_refs = [(ref, surf) for ref, surf in surfaces if surf.stype == axis]
        if not cyl_refs:
            return None
        neg_r = [surf.params[0] for ref, surf in cyl_refs if ref.sense < 0]
        pos_r = [surf.params[0] for ref, surf in cyl_refs if ref.sense > 0]
        if neg_r and pos_r:
            rmax = max(neg_r)
            rmin = min(pos_r)
            if rmin >= rmax:
                return None
        elif neg_r and not pos_r:
            rmax = min(neg_r)
            rmin = 0.0
        else:
            return None

        key = ("cyl", _round_key(rmin), _round_key(rmax), _round_key(length))
        name = ctx["prim_cache"].get(key)
        if name is None:
            idx = ctx["prim_counter"]
            ctx["prim_counter"] += 1
            name = f"PrimCyl_{idx}"
            ctx["gdml"].add_solid(GTube(name, rmax, length, rmin))
            ctx["solid_names"].add(name)
            ctx["eval_solids"][name] = EvalTube(rmax, length, rmin)
            ctx["prim_cache"][key] = name
        return name, center, rot, "cylinder"

    # Sphere recognition: SO/SPH shells with common center.
    if unique_types.issubset({MSurfType.SO, MSurfType.SPH}):
        centers = []
        neg_r = []
        pos_r = []
        for ref, surf in surfaces:
            if surf.stype == MSurfType.SO:
                centers.append((sx, sy, sz))
                r = surf.params[0]
            else:
                if len(surf.params) >= 4:
                    x0, y0, z0, r = surf.params[0:4]
                elif len(surf.params) == 1:
                    x0, y0, z0, r = 0.0, 0.0, 0.0, surf.params[0]
                else:
                    return None
                centers.append((x0 + sx, y0 + sy, z0 + sz))
            if ref.sense < 0:
                neg_r.append(r)
            else:
                pos_r.append(r)

        c0 = centers[0]
        for c in centers[1:]:
            if abs(c[0] - c0[0]) > 1e-8 or abs(c[1] - c0[1]) > 1e-8 or abs(c[2] - c0[2]) > 1e-8:
                return None

        if neg_r and pos_r:
            rmax = max(neg_r)
            rmin = min(pos_r)
            if rmin >= rmax:
                return None
        elif neg_r and not pos_r:
            rmax = min(neg_r)
            rmin = 0.0
        else:
            return None
        key = ("sph", _round_key(rmin), _round_key(rmax))
        name = ctx["prim_cache"].get(key)
        if name is None:
            idx = ctx["prim_counter"]
            ctx["prim_counter"] += 1
            name = f"PrimSph_{idx}"
            ctx["gdml"].add_solid(GSphere(name, rmax, rmin))
            ctx["solid_names"].add(name)
            ctx["eval_solids"][name] = EvalSphere(rmax, rmin)
            ctx["prim_cache"][key] = name
        return name, c0, (0.0, 0.0, 0.0), "sphere"

    return None


def _surface_primitive_for_subtraction(surf, ctx):
    bbox = ctx["bbox"]
    gdml_model = ctx["gdml"]
    sx, sy, sz = bbox["shift"]

    def _ensure_tube(name, rmax, length, rmin=0.0):
        if name not in ctx["solid_names"]:
            gdml_model.add_solid(GTube(name, rmax, length, rmin))
            ctx["solid_names"].add(name)
            ctx["eval_solids"][name] = EvalTube(rmax, length, rmin)
        return name

    if surf.stype in (MSurfType.CX, MSurfType.C_X):
        if surf.stype == MSurfType.C_X and len(surf.params) >= 3:
            cy0, cz0, rmax = surf.params[0:3]
            pos = (0.0, cy0 + sy, cz0 + sz)
        else:
            rmax = surf.params[0]
            pos = (0.0, sy, sz)
        return _ensure_tube(f"CutCyl_X_{surf.sid}", rmax, 2 * bbox["hx"]), pos, (0.0, 90.0, 0.0)

    if surf.stype in (MSurfType.CY, MSurfType.C_Y):
        if surf.stype == MSurfType.C_Y and len(surf.params) >= 3:
            cx0, cz0, rmax = surf.params[0:3]
            pos = (cx0 + sx, 0.0, cz0 + sz)
        else:
            rmax = surf.params[0]
            pos = (sx, 0.0, sz)
        return _ensure_tube(f"CutCyl_Y_{surf.sid}", rmax, 2 * bbox["hy"]), pos, (-90.0, 0.0, 0.0)

    if surf.stype in (MSurfType.CZ, MSurfType.C_Z):
        if surf.stype == MSurfType.C_Z and len(surf.params) >= 3:
            cx0, cy0, rmax = surf.params[0:3]
            pos = (cx0 + sx, cy0 + sy, 0.0)
        else:
            rmax = surf.params[0]
            pos = (sx, sy, 0.0)
        return _ensure_tube(f"CutCyl_Z_{surf.sid}", rmax, 2 * bbox["hz"]), pos, (0.0, 0.0, 0.0)

    if surf.stype in (MSurfType.SO, MSurfType.SPH):
        if surf.stype == MSurfType.SPH:
            if len(surf.params) >= 4:
                x0, y0, z0, rmax = surf.params[0:4]
            elif len(surf.params) == 1:
                x0, y0, z0, rmax = 0.0, 0.0, 0.0, surf.params[0]
            else:
                return None
            pos = (x0 + sx, y0 + sy, z0 + sz)
        else:
            rmax = surf.params[0]
            pos = (sx, sy, sz)
        name = f"CutSph_{surf.sid}"
        if name not in ctx["solid_names"]:
            gdml_model.add_solid(GSphere(name, rmax))
            ctx["solid_names"].add(name)
            ctx["eval_solids"][name] = EvalSphere(rmax)
        return name, pos, (0.0, 0.0, 0.0)

    if surf.stype == MSurfType.RPP and len(surf.params) >= 6:
        x0, x1, y0, y1, z0, z1 = surf.params[0:6]
        xmin, xmax = min(x0, x1) + sx, max(x0, x1) + sx
        ymin, ymax = min(y0, y1) + sy, max(y0, y1) + sy
        zmin, zmax = min(z0, z1) + sz, max(z0, z1) + sz
        xlen, ylen, zlen = xmax - xmin, ymax - ymin, zmax - zmin
        pos = (0.5 * (xmin + xmax), 0.5 * (ymin + ymax), 0.5 * (zmin + zmax))
        name = f"CutRPP_{surf.sid}"
        if name not in ctx["solid_names"]:
            gdml_model.add_solid(GBox(name, xlen, ylen, zlen))
            ctx["solid_names"].add(name)
            ctx["eval_solids"][name] = EvalBox(xlen, ylen, zlen)
        return name, pos, (0.0, 0.0, 0.0)

    if surf.stype == MSurfType.BOX and len(surf.params) >= 12:
        x0, y0, z0, *rest = surf.params[0:12]
        a, b, c = tuple(rest[0:3]), tuple(rest[3:6]), tuple(rest[6:9])
        lengths = (_norm3(a), _norm3(b), _norm3(c))
        if min(lengths) <= 1e-12:
            return None
        e1, e2, e3 = _unit3(a), _unit3(b), _unit3(c)
        if max(abs(_dot3(e1, e2)), abs(_dot3(e1, e3)), abs(_dot3(e2, e3))) > 1e-7:
            return None
        matrix = [
            [e1[0], e2[0], e3[0]],
            [e1[1], e2[1], e3[1]],
            [e1[2], e2[2], e3[2]],
        ]
        rot = _matrix_to_euler_deg_zyx(matrix)
        pos = (
            x0 + 0.5 * (a[0] + b[0] + c[0]) + sx,
            y0 + 0.5 * (a[1] + b[1] + c[1]) + sy,
            z0 + 0.5 * (a[2] + b[2] + c[2]) + sz,
        )
        name = f"CutBOX_{surf.sid}"
        if name not in ctx["solid_names"]:
            gdml_model.add_solid(GBox(name, *lengths))
            ctx["solid_names"].add(name)
            ctx["eval_solids"][name] = EvalBox(*lengths)
        return name, pos, rot

    if surf.stype == MSurfType.RCC and len(surf.params) >= 7:
        x0, y0, z0, hx, hy, hz, rmax = surf.params[0:7]
        length = _norm3((hx, hy, hz))
        if length <= 0.0:
            return None
        rot = _rotation_from_z((hx, hy, hz))
        pos = (x0 + 0.5 * hx + sx, y0 + 0.5 * hy + sy, z0 + 0.5 * hz + sz)
        name = f"CutRCC_{surf.sid}"
        if name not in ctx["solid_names"]:
            gdml_model.add_solid(GTube(name, rmax, length))
            ctx["solid_names"].add(name)
            ctx["eval_solids"][name] = EvalTube(rmax, length)
        return name, pos, rot

    return None


def _build_solid_from_expr(node, cell_id, ctx, allow_templates=True, stack=()):
    gdml_model = ctx["gdml"]

    if allow_templates:
        prim = _try_build_primitive(node, cell_id, ctx)
        if prim is not None:
            name, pos, rot, prim_kind = prim
            if ctx.get("log"):
                print(f"[info] Cell {cell_id} matched primitive template: {prim_kind}")
            return name, pos, rot

    if isinstance(node, ComplementNode):
        child_name, child_pos, child_rot = _build_solid_from_expr(node.child, cell_id, ctx, allow_templates, stack)
        idx = ctx["bool_counter"]
        ctx["bool_counter"] += 1
        name = f"Bool_{cell_id}_{idx}"
        pos_vec = _make_vec(f"Pos_{name}", "position", "cm", child_pos)
        rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", child_rot)
        gsolid = GBooleanSolid(name, "subtraction", ctx["bbox_name"], child_name, pos_vec, rot_vec)
        gdml_model.add_solid(gsolid)
        ctx["eval_solids"][name] = EvalBoolean("subtraction", ctx["eval_solids"][ctx["bbox_name"]], ctx["eval_solids"][child_name], child_pos, child_rot)
        return name, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    if isinstance(node, SurfaceRef):
        resolve_surface = ctx.get("resolve_surface")
        surf = resolve_surface(node.sid) if resolve_surface is not None else ctx["surface_map"].get(node.sid)
        if surf is None:
            raise ValueError(f"Surface {node.sid} not found in model")
        return _solid_from_surface(surf, node.sense, ctx), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    if isinstance(node, CellRef):
        resolver = ctx.get("resolve_cell")
        if resolver is None:
            raise ValueError("Cell reference resolver is not configured")
        return resolver(node.cid, stack)

    if isinstance(node, UnionNode) or isinstance(node, IntersectionNode):
        if isinstance(node, IntersectionNode):
            positive_ref = None
            minuend_node = None
            if isinstance(node.left, SurfaceRef) and node.left.sense > 0:
                positive_ref = node.left
                minuend_node = node.right
            elif isinstance(node.right, SurfaceRef) and node.right.sense > 0:
                positive_ref = node.right
                minuend_node = node.left

            if positive_ref is not None:
                resolve_surface = ctx.get("resolve_surface")
                surf = resolve_surface(positive_ref.sid) if resolve_surface is not None else ctx["surface_map"].get(positive_ref.sid)
                if surf is None:
                    raise ValueError(f"Surface {positive_ref.sid} not found in model")
                cut_prim = _surface_primitive_for_subtraction(surf, ctx)
                if cut_prim is not None:
                    minuend_primitive = None
                    if (
                        allow_templates
                        and isinstance(minuend_node, SurfaceRef)
                        and minuend_node.sense < 0
                    ):
                        minuend_surf = (
                            resolve_surface(minuend_node.sid)
                            if resolve_surface is not None
                            else ctx["surface_map"].get(minuend_node.sid)
                        )
                        if minuend_surf is not None and minuend_surf.stype in {
                            MSurfType.SO,
                            MSurfType.SPH,
                            MSurfType.RPP,
                            MSurfType.BOX,
                            MSurfType.RCC,
                        }:
                            minuend_primitive = _surface_primitive_for_subtraction(
                                minuend_surf, ctx
                            )
                    if minuend_primitive is not None:
                        minuend_name, minuend_pos, minuend_rot = minuend_primitive
                    else:
                        minuend_name, minuend_pos, minuend_rot = _build_solid_from_expr(
                            minuend_node, cell_id, ctx, allow_templates, stack
                        )
                    sub_name, sub_pos, sub_rot = cut_prim
                    rel_pos, rel_rot = _relative_pose(
                        minuend_pos, minuend_rot, sub_pos, sub_rot
                    )
                    idx = ctx["bool_counter"]
                    ctx["bool_counter"] += 1
                    name = f"Bool_{cell_id}_{idx}"
                    pos_vec = _make_vec(f"Pos_{name}", "position", "cm", rel_pos)
                    rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rel_rot)
                    gsolid = GBooleanSolid(name, "subtraction", minuend_name, sub_name, pos_vec, rot_vec)
                    gdml_model.add_solid(gsolid)
                    ctx["eval_solids"][name] = EvalBoolean(
                        "subtraction", ctx["eval_solids"][minuend_name],
                        ctx["eval_solids"][sub_name], rel_pos, rel_rot
                    )
                    if ctx.get("log"):
                        print(f"[info] Cell {cell_id} lowered positive surface {positive_ref.sid} as subtraction primitive")
                    return name, minuend_pos, minuend_rot

            if isinstance(node.left, ComplementNode) ^ isinstance(node.right, ComplementNode):
                if isinstance(node.left, ComplementNode):
                    minuend_node = node.right
                    sub_node = node.left.child
                else:
                    minuend_node = node.left
                    sub_node = node.right.child

                minuend_name, minuend_pos, minuend_rot = _build_solid_from_expr(
                    minuend_node, cell_id, ctx, allow_templates, stack
                )
                if not _is_zero_transform(minuend_pos, minuend_rot):
                    minuend_name, minuend_pos, minuend_rot = _build_solid_from_expr(
                        minuend_node, cell_id, ctx, allow_templates=False, stack=stack
                    )

                sub_name, sub_pos, sub_rot = _build_solid_from_expr(sub_node, cell_id, ctx, allow_templates, stack)
                if not _is_zero_transform(minuend_pos, minuend_rot):
                    sub_name, sub_pos, sub_rot = _build_solid_from_expr(
                        sub_node, cell_id, ctx, allow_templates=False, stack=stack
                    )

                idx = ctx["bool_counter"]
                ctx["bool_counter"] += 1
                name = f"Bool_{cell_id}_{idx}"
                pos_vec = _make_vec(f"Pos_{name}", "position", "cm", sub_pos)
                rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", sub_rot)
                gsolid = GBooleanSolid(name, "subtraction", minuend_name, sub_name, pos_vec, rot_vec)
                gdml_model.add_solid(gsolid)
                ctx["eval_solids"][name] = EvalBoolean("subtraction", ctx["eval_solids"][minuend_name], ctx["eval_solids"][sub_name], sub_pos, sub_rot)
                return name, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

        left_name, left_pos, left_rot = _build_solid_from_expr(node.left, cell_id, ctx, allow_templates, stack)
        right_name, right_pos, right_rot = _build_solid_from_expr(node.right, cell_id, ctx, allow_templates, stack)
        btype = "union" if isinstance(node, UnionNode) else "intersection"

        if not _is_zero_transform(left_pos, left_rot) and not _is_zero_transform(right_pos, right_rot):
            right_name, right_pos, right_rot = _build_solid_from_expr(
                node.right, cell_id, ctx, allow_templates=False, stack=stack
            )
        if not _is_zero_transform(left_pos, left_rot) and not _is_zero_transform(right_pos, right_rot):
            left_name, left_pos, left_rot = _build_solid_from_expr(
                node.left, cell_id, ctx, allow_templates=False, stack=stack
            )

        # Ensure at most one side has transform; if left has transform, swap (union/intersection commutative)
        if _is_zero_transform(left_pos, left_rot) and not _is_zero_transform(right_pos, right_rot):
            first_name, second_name = left_name, right_name
            pos, rot = right_pos, right_rot
        elif not _is_zero_transform(left_pos, left_rot) and _is_zero_transform(right_pos, right_rot):
            first_name, second_name = right_name, left_name
            pos, rot = left_pos, left_rot
        else:
            first_name, second_name = left_name, right_name
            pos, rot = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

        idx = ctx["bool_counter"]
        ctx["bool_counter"] += 1
        name = f"Bool_{cell_id}_{idx}"

        pos_vec = _make_vec(f"Pos_{name}", "position", "cm", pos)
        rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rot)
        gsolid = GBooleanSolid(name, btype, first_name, second_name, pos_vec, rot_vec)
        gdml_model.add_solid(gsolid)
        ctx["eval_solids"][name] = EvalBoolean(btype, ctx["eval_solids"][first_name], ctx["eval_solids"][second_name], pos, rot)
        return name, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    raise ValueError(f"Unknown expression node type: {type(node)}")


def mcnp2Gdml(
    mcnp_model: MModel,
    gdml_model: GModel,
    top_cells,
    bbox_override,
    bbox_margin,
    dump_geom,
    log_enabled=False,
    validate=None,
    return_debug=False,
):
    name = mcnp_model.name
    gdml_model.set_name(name)

    PI = GConstant("PI", 3.14159265358979)
    gdml_model.add_define(PI)

    TWOPI = GConstant("TWOPI", 6.28318530717959)
    gdml_model.add_define(TWOPI)

    HALFPI = GConstant("HALFPI", 1.5707963267949)
    gdml_model.add_define(HALFPI)

    center = GVector("center", "position", "cm", x=0.0, y=0.0, z=0.0)
    gdml_model.add_define(center)

    identity = GVector("identity", "rotation", "deg", x=0.0, y=0.0, z=0.0)
    gdml_model.add_define(identity)

    gElem_O = GElement("Oxygen", 8, "O", 16.0)
    gElem_N = GElement("Nitrogen", 7, "N", 14.01)
    gMixture_air = GMixture("Air", 0.001129)
    gMixture_air.add_fraction("Oxygen", 0.3)
    gMixture_air.add_fraction("Nitrogen", 0.7)
    gdml_model.add_material(gElem_O)
    gdml_model.add_material(gElem_N)
    gdml_model.add_material(gMixture_air)

    mmaterials = mcnp_model.materials
    cells_by_material = {}
    for cell in mcnp_model.cells:
        if cell.mat_id > 0:
            cells_by_material.setdefault(cell.mat_id, []).append(cell)
    elem_list = []
    material_name_by_cell_id = {}
    defined_material_ids = set()
    for mmat in mmaterials:
        defined_material_ids.add(mmat.mat_id)
        mfractions = mmat.fractions
        raw_values = list(mfractions.values())
        if any(value < 0.0 for value in raw_values) and any(value > 0.0 for value in raw_values):
            raise ValueError(f"Material {mmat.name} mixes atom and mass fraction signs")

        if raw_values and all(value <= 0.0 for value in raw_values):
            weights = {elem: abs(value) for elem, value in mfractions.items()}
        else:
            # Positive MCNP entries are atom proportions; GDML fractions are
            # mass fractions, so multiply by atomic mass before normalising.
            weights = {elem: abs(value) * elem.mass for elem, value in mfractions.items()}
        total_weight = sum(weights.values())
        if mfractions and total_weight <= 0.0:
            if len(mfractions) == 1:
                weights = {next(iter(mfractions)): 1.0}
                total_weight = 1.0
            else:
                print(
                    f"[warn] Material {mmat.name} lacks atomic masses; "
                    "normalising atom proportions as approximate mass fractions."
                )
                weights = {elem: abs(value) for elem, value in mfractions.items()}
                total_weight = sum(weights.values())
        mass_fractions = {
            elem: weight / total_weight for elem, weight in weights.items()
        } if total_weight > 0.0 else {}

        atom_average_mass = 0.0
        if raw_values and all(value >= 0.0 for value in raw_values):
            atom_total = sum(raw_values)
            if atom_total > 0.0:
                atom_average_mass = sum(
                    value * elem.mass for elem, value in mfractions.items()
                ) / atom_total
        material_cells = cells_by_material.get(mmat.mat_id, [])
        cell_densities = []
        for cell in material_cells:
            converted_density = None
            if cell.density < 0.0:
                converted_density = abs(cell.density)
            elif cell.density > 0.0 and atom_average_mass > 0.0:
                converted_density = cell.density * atom_average_mass / 0.602214076
            if converted_density is not None:
                cell_densities.append((cell, converted_density))
        if material_cells and not cell_densities:
            print(f"[warn] Material {mmat.name} has no convertible cell density; using 1 g/cm3.")

        for melem in mfractions.keys():
            if melem.name not in elem_list:
                mass_number = int(melem.name[-3:])
                if mass_number > 0:
                    isotope_name = f"Iso{melem.name:>06s}"
                    isotope = GIsotope(
                        isotope_name,
                        melem.ZZZ,
                        mass_number,
                        float(mass_number),
                    )
                    gdml_model.add_material(isotope)
                    gelem = GElement(
                        f"E{melem.name:>06s}",
                        melem.ZZZ,
                        f"{melem.ZZZ:>03d}",
                        float(mass_number),
                        isotope_ref=isotope_name,
                    )
                else:
                    gelem = GElement(
                        f"E{melem.name:>06s}", melem.ZZZ,
                        f"{melem.ZZZ:>03d}", melem.mass,
                    )
                gdml_model.add_material(gelem)
                elem_list.append(melem.name)

        # MCNP assigns density on each cell, whereas GDML assigns it to a
        # material.  Preserve this distinction by creating one material
        # variant for every distinct density used by the same composition.
        density_groups = []
        for cell, density in cell_densities:
            group_index = None
            for i, group in enumerate(density_groups):
                if math.isclose(density, group["density"], rel_tol=1e-6, abs_tol=1e-9):
                    group_index = i
                    break
            if group_index is None:
                density_groups.append({"density": density, "cells": [cell]})
            else:
                density_groups[group_index]["cells"].append(cell)
        if not density_groups:
            density_groups = [{"density": 1.0, "cells": material_cells}]

        multiple = len(density_groups) > 1
        for index, group in enumerate(density_groups, 1):
            density = group["density"]
            if multiple:
                tag = f"{density:.8g}".replace("-", "m").replace("+", "").replace(".", "p")
                material_name = f"{mmat.name}_rho{index}_{tag}"
            else:
                material_name = mmat.name
            gmat = GMixture(material_name, density)
            for melem in mfractions.keys():
                gmat.add_fraction(f"E{melem.name:>06s}", mass_fractions[melem])
            gdml_model.add_material(gmat)
            for cell in group["cells"]:
                material_name_by_cell_id[cell.cell_id] = material_name

    # Geometry-only decks sometimes retain material numbers and densities but
    # omit all M cards.  Keep the GDML reference graph loadable and make the
    # missing source information explicit; the placeholder must not be counted
    # as a successful material-composition conversion.
    for mat_id, material_cells in cells_by_material.items():
        if mat_id in defined_material_ids:
            continue
        base_name = f"M{mat_id:>08d}"
        print(
            f"[warn] Material {base_name} is referenced but has no M card; "
            "using an Air-composition placeholder."
        )
        density_groups = []
        for cell in material_cells:
            density = abs(cell.density) if cell.density < 0.0 else 1.0
            group = next(
                (
                    item for item in density_groups
                    if math.isclose(density, item["density"], rel_tol=1e-6, abs_tol=1e-9)
                ),
                None,
            )
            if group is None:
                group = {"density": density, "cells": []}
                density_groups.append(group)
            group["cells"].append(cell)
        for index, group in enumerate(density_groups, 1):
            if len(density_groups) == 1:
                material_name = base_name
            else:
                tag = f"{group['density']:.8g}".replace("-", "m").replace("+", "").replace(".", "p")
                material_name = f"{base_name}_rho{index}_{tag}"
            gmat = GMixture(material_name, group["density"])
            gmat.add_fraction("Oxygen", 0.3)
            gmat.add_fraction("Nitrogen", 0.7)
            gdml_model.add_material(gmat)
            for cell in group["cells"]:
                material_name_by_cell_id[cell.cell_id] = material_name

    transformed_surfaces = [
        surf for surf in mcnp_model.surfaces
        if getattr(surf, "transform_id", None) is not None
    ]
    if transformed_surfaces:
        sample = ", ".join(
            f"{surf.sid}(TR{surf.transform_id})" for surf in transformed_surfaces[:8]
        )
        suffix = " ..." if len(transformed_surfaces) > 8 else ""
        raise NotImplementedError(
            "Surface transformation cards are parsed but not yet converted: "
            f"{sample}{suffix}"
        )

    bbox = _compute_bbox(mcnp_model.surfaces, bbox_margin, bbox_override)
    if bbox_override is None:
        # Surface extents alone do not bound cells that are subsequently
        # placed by TRCL or FILL transforms.  Reserve room for two composed
        # placement levels, which covers the supported universe/FILL nesting
        # while retaining the source-derived centre and clipping scale.
        tr_map_for_bbox = getattr(mcnp_model, "transforms", {})
        placement_positions = []
        for cell in mcnp_model.cells:
            trcl_raw = getattr(cell, "key_opts", {}).get("TRCL", "")
            if trcl_raw:
                placement_positions.append(_parse_transform_from_raw(trcl_raw, tr_map_for_bbox)[0])
            fill_spec = getattr(cell, "fill", None)
            if fill_spec is None:
                continue
            if fill_spec.transform:
                placement_positions.append(
                    _parse_transform_from_raw(fill_spec.transform, tr_map_for_bbox, is_star=fill_spec.is_star)[0]
                )
            for raw in fill_spec.entry_transforms or ():
                if raw:
                    placement_positions.append(
                        _parse_transform_from_raw(raw, tr_map_for_bbox, is_star=fill_spec.is_star)[0]
                    )
        if placement_positions:
            padding = [2.0 * max(abs(pos[i]) for pos in placement_positions) for i in range(3)]
            bbox["hx"] += padding[0]
            bbox["hy"] += padding[1]
            bbox["hz"] += padding[2]
    bbox_solid = GBox("BBox", 2 * bbox["hx"], 2 * bbox["hy"], 2 * bbox["hz"])
    gdml_model.add_solid(bbox_solid)

    surface_map = {s.sid: s for s in mcnp_model.surfaces}
    surf_alias_seen = set()
    transformed_surface_alias_cache = {}
    cell_by_id_for_surface = {cell.cell_id: cell for cell in mcnp_model.cells}

    def _resolve_surface(sid):
        surf = surface_map.get(sid)
        if surf is not None:
            return surf
        # MCNP permits a surface from a transformed cell to be referenced as
        # ``<cell-id><three-digit-surface-id>``.  For example, 1038038 means
        # surface 38 in cell 1038's TRCL frame.  Falling back to surface 38
        # alone silently discards the placement transform and makes enclosing
        # basket/duct cells overlap their translated filled universes.
        if sid >= 1000:
            alias_cell_id, base_sid = divmod(sid, 1000)
            alias_cell = cell_by_id_for_surface.get(alias_cell_id)
            base_surf = surface_map.get(base_sid)
            trcl_raw = getattr(alias_cell, "key_opts", {}).get("TRCL", "") if alias_cell else ""
            if base_surf is not None and trcl_raw:
                cached = transformed_surface_alias_cache.get(sid)
                if cached is None:
                    tpos, trot = _parse_transform_from_raw(
                        trcl_raw, getattr(mcnp_model, "transforms", {})
                    )
                    transformed = MModel._surface_to_global(
                        base_surf, {"pos": tpos, "rot": trot}
                    )
                    # The same base surface can be referenced through several
                    # transformed owning cells.  Preserve the full alias id so
                    # the half-space cache cannot merge distinct placements.
                    cached = MSurface(
                        sid, transformed.stype, list(transformed.params),
                        transformed.transform_id, transformed.boundary,
                    )
                    transformed_surface_alias_cache[sid] = cached
                return cached
        for mod in (1000, 10000, 100000):
            base = sid % mod
            if base in surface_map:
                if sid not in surf_alias_seen:
                    surf_alias_seen.add(sid)
                    if log_enabled:
                        print(f"[warn] Surface {sid} not found; fallback to base surface {base}.")
                return surface_map[base]
        return None

    ctx = {
        "gdml": gdml_model,
        "surface_map": surface_map,
        "resolve_surface": _resolve_surface,
        "bbox": bbox,
        "bbox_name": bbox_solid.name,
        "halfspace_cache": {},
        "solid_names": {bbox_solid.name},
        "bool_counter": 0,
        "prim_counter": 0,
        "prim_cache": {},
        "log": log_enabled,
        "eval_solids": {},
    }
    ctx["eval_solids"][bbox_solid.name] = EvalBox(2 * bbox["hx"], 2 * bbox["hy"], 2 * bbox["hz"])

    cell_place = {}
    define_cache = {"center": (0.0, 0.0, 0.0), "identity": (0.0, 0.0, 0.0)}
    cell_roots = {}
    geom_dump = {}

    mcells = mcnp_model.cells
    cell_by_id = {c.cell_id: c for c in mcells}
    universes = getattr(mcnp_model, "universes", {})
    has_universe = any(getattr(c, "universe", 0) != 0 for c in mcells)
    has_fill = any(getattr(c, "fill", None) is not None for c in mcells)
    has_lat = any(getattr(c, "lat", 0) != 0 for c in mcells)
    max_lattice_instances = 5000

    def _fill_supported(cell):
        fs = getattr(cell, "fill", None)
        if fs is None:
            return True
        if fs.ranges is None and fs.entries is None:
            return fs.universe is not None
        if fs.ranges is None or fs.entries is None:
            return False
        if len(fs.ranges) not in (2, 3):
            return False
        return True

    if has_lat and log_enabled:
        print(
            "[info] LAT detected. Support: FILL=<universe>, indexed FILL ranges for LAT=1, "
            "and RHP-based indexed LAT=2 fills."
        )
    for c in mcells:
        fs = getattr(c, "fill", None)
        if fs is not None and not _fill_supported(c):
            print(f"[warn] Cell {c.cell_id} has unsupported FILL syntax '{fs.raw}'. Fallback to direct cell geometry.")

    sx, sy, sz = bbox["shift"]
    tr_map = getattr(mcnp_model, "transforms", {})

    def _cell_trcl_pose(cell):
        raw = getattr(cell, "key_opts", {}).get("TRCL", "")
        return _parse_transform_from_raw(raw, tr_map)

    def _cell_plane_bounds(cell):
        refs = _extract_intersection_surfaces(cell.geom_AST)
        if refs is None:
            return None

        lo = {"x": -float("inf"), "y": -float("inf"), "z": -float("inf")}
        hi = {"x": float("inf"), "y": float("inf"), "z": float("inf")}
        any_plane = False
        resolve_surface = ctx.get("resolve_surface")
        for ref in refs:
            surf = resolve_surface(ref.sid) if resolve_surface is not None else surface_map.get(ref.sid)
            if surf is None:
                continue
            axis = None
            cval = 0.0
            if surf.stype == MSurfType.PX:
                axis = "x"
                cval = surf.params[0] + sx
            elif surf.stype == MSurfType.PY:
                axis = "y"
                cval = surf.params[0] + sy
            elif surf.stype == MSurfType.PZ:
                axis = "z"
                cval = surf.params[0] + sz
            elif surf.stype == MSurfType.RPP and len(surf.params) >= 6 and ref.sense < 0:
                x0, x1, y0, y1, z0, z1 = surf.params[0:6]
                lo["x"] = max(lo["x"], min(x0, x1) + sx)
                hi["x"] = min(hi["x"], max(x0, x1) + sx)
                lo["y"] = max(lo["y"], min(y0, y1) + sy)
                hi["y"] = min(hi["y"], max(y0, y1) + sy)
                lo["z"] = max(lo["z"], min(z0, z1) + sz)
                hi["z"] = min(hi["z"], max(z0, z1) + sz)
                any_plane = True
                continue
            if axis is None:
                continue
            any_plane = True
            if ref.sense < 0:
                hi[axis] = min(hi[axis], cval)
            else:
                lo[axis] = max(lo[axis], cval)

        if not any_plane:
            return None

        out = {}
        for axis in ("x", "y", "z"):
            if lo[axis] > -float("inf") and hi[axis] < float("inf") and lo[axis] < hi[axis]:
                out[axis] = (lo[axis], hi[axis])
            else:
                out[axis] = None
        return out

    def _intersect_bounds(a, b):
        if a is None and b is None:
            return None
        out = {}
        for axis in ("x", "y", "z"):
            pa = None if a is None else a.get(axis)
            pb = None if b is None else b.get(axis)
            if pa is None and pb is None:
                out[axis] = None
            elif pa is None:
                out[axis] = pb
            elif pb is None:
                out[axis] = pa
            else:
                lo = max(pa[0], pb[0])
                hi = min(pa[1], pb[1])
                if lo >= hi:
                    return None
                out[axis] = (lo, hi)
        return out

    def _translate_bounds(b, delta):
        if b is None:
            return None
        dx, dy, dz = delta
        out = {}
        for axis, d in (("x", dx), ("y", dy), ("z", dz)):
            p = b.get(axis)
            out[axis] = None if p is None else (p[0] + d, p[1] + d)
        return out

    def _cell_lattice_vectors(cell):
        """Recover rectangular-lattice pitch vectors from paired planes.

        Surface transforms turn PX/PY/PZ cards into general P cards.  Their
        axis-aligned bounding box is then unavailable, but the distance and
        direction between each pair of parallel bounding planes still define
        the lattice basis exactly.
        """
        refs = _extract_intersection_surfaces(cell.geom_AST)
        if refs is None:
            return []
        resolve_surface = ctx.get("resolve_surface")
        groups = []
        for ref in refs:
            surf = resolve_surface(ref.sid) if resolve_surface is not None else surface_map.get(ref.sid)
            if surf is None:
                continue
            if surf.stype == MSurfType.PX:
                normal, distance = (1.0, 0.0, 0.0), surf.params[0]
            elif surf.stype == MSurfType.PY:
                normal, distance = (0.0, 1.0, 0.0), surf.params[0]
            elif surf.stype == MSurfType.PZ:
                normal, distance = (0.0, 0.0, 1.0), surf.params[0]
            elif surf.stype == MSurfType.P and len(surf.params) >= 4:
                normal, distance = tuple(surf.params[:3]), surf.params[3]
            else:
                continue
            norm = math.sqrt(sum(v * v for v in normal))
            if norm <= 1e-14:
                continue
            unit = tuple(v / norm for v in normal)
            q = distance / norm
            # Canonicalize the normal direction so antiparallel plane cards
            # join the same group and their signed offsets remain comparable.
            for component in unit:
                if abs(component) > 1e-10:
                    if component < 0.0:
                        unit = tuple(-v for v in unit)
                        q = -q
                    break
            match = None
            for group in groups:
                dot = sum(a * b for a, b in zip(unit, group["unit"]))
                if abs(dot - 1.0) < 1e-7:
                    match = group
                    break
            if match is None:
                match = {"unit": unit, "offsets": []}
                groups.append(match)
            match["offsets"].append(q)

        vectors = []
        center = [0.0, 0.0, 0.0]
        for group in groups:
            offsets = group["offsets"]
            if len(offsets) < 2:
                continue
            pitch = max(offsets) - min(offsets)
            if pitch <= 1e-10:
                continue
            unit = group["unit"]
            vectors.append(tuple(pitch * v for v in unit))
            midpoint = 0.5 * (max(offsets) + min(offsets))
            for i in range(3):
                center[i] += midpoint * unit[i]
            if len(vectors) == 3:
                break
        return vectors, tuple(center)

    def _cell_hex_lattice_vectors(cell):
        """Return the two centre-to-centre vectors of an RHP-based LAT=2 cell.

        MCNP's RHP transverse vector points along a face normal and has the
        apothem magnitude.  Neighbouring hexagonal lattice cells are therefore
        separated by twice that magnitude along a face normal, with the second
        basis vector rotated by 60 degrees in the transverse plane.
        """
        refs = _extract_intersection_surfaces(cell.geom_AST)
        if refs is None:
            return None
        resolve_surface = ctx.get("resolve_surface")
        for ref in refs:
            if ref.sense >= 0:
                continue
            surf = resolve_surface(ref.sid) if resolve_surface is not None else surface_map.get(ref.sid)
            if surf is None or surf.stype != MSurfType.RHP or len(surf.params) < 9:
                continue
            hx, hy, hz = surf.params[3:6]
            ux, uy, uz = surf.params[6:9]
            axis = _unit3((hx, hy, hz))
            if _norm3(axis) <= 1e-12:
                continue
            parallel = _dot3((ux, uy, uz), axis)
            face_normal = (ux - parallel * axis[0], uy - parallel * axis[1], uz - parallel * axis[2])
            apothem = _norm3(face_normal)
            if apothem <= 1e-12:
                continue
            e1 = _unit3(face_normal)
            e2 = _cross3(axis, e1)
            pitch = 2.0 * apothem
            sx, sy, sz = bbox["shift"]
            center = (surf.params[0] + 0.5 * hx + sx,
                      surf.params[1] + 0.5 * hy + sy,
                      surf.params[2] + 0.5 * hz + sz)
            return (
                (
                    tuple(pitch * value for value in e1),
                    tuple(pitch * (0.5 * e1[i] + math.sqrt(3.0) * 0.5 * e2[i]) for i in range(3)),
                ),
                center,
            )
        return None

    cell_bounds = {c.cell_id: _cell_plane_bounds(c) for c in mcells}
    ctx["cell_bounds"] = cell_bounds
    building_cells = set()
    cell_template_enabled = {}

    def _ensure_cell_root(cell_id: int, stack=()):
        if cell_id in cell_roots:
            pos, rot = cell_place.get(cell_id, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
            return cell_roots[cell_id], pos, rot

        if cell_id in building_cells:
            print(f"[warn] Recursive #cell reference detected for cell {cell_id}; fallback to BBox.")
            return ctx["bbox_name"], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

        mcell = cell_by_id.get(cell_id)
        if mcell is None:
            print(f"[warn] Referenced cell {cell_id} not found; fallback to BBox.")
            return ctx["bbox_name"], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

        building_cells.add(cell_id)
        try:
            if ctx.get("log"):
                norm = expr_to_str(mcell.geom_AST)
                if norm != mcell.raw_geom_expr:
                    print(f"[debug] Cell {mcell.cell_id} expr: {mcell.raw_geom_expr} -> {norm}")
            geom_ast = mcell.geom_AST
            template_enabled = (
                not has_fill
                or (
                    getattr(mcell, "universe", 0) == 0
                    and getattr(mcell, "fill", None) is None
                    and getattr(mcell, "lat", 0) == 0
                )
            )
            cell_template_enabled[mcell.cell_id] = template_enabled
            root_solid_name, pos, rot = _build_solid_from_expr(
                geom_ast,
                mcell.cell_id,
                ctx,
                allow_templates=template_enabled,
                stack=stack + (cell_id,),
            )
            cell_place[mcell.cell_id] = (pos, rot)
            cell_roots[mcell.cell_id] = root_solid_name
            if dump_geom:
                geom_dump[mcell.cell_id] = geom_ast.to_dict()
            return root_solid_name, pos, rot
        finally:
            building_cells.remove(cell_id)

    def _resolve_cell_ref(ref_cell_id: int, stack):
        if ref_cell_id in stack:
            print(f"[warn] Cyclic #cell expression at cell {ref_cell_id}; fallback to BBox.")
            return ctx["bbox_name"], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        root_name, pos, rot = _ensure_cell_root(ref_cell_id, stack)
        ref_cell = cell_by_id.get(ref_cell_id)
        if ref_cell is not None:
            tpos, trot = _cell_trcl_pose(ref_cell)
            pos, rot = _compose_pose(pos, rot, tpos, trot)
        return root_name, pos, rot

    ctx["resolve_cell"] = _resolve_cell_ref

    for mcell in mcells:
        _ensure_cell_root(mcell.cell_id, tuple())

    world_vol = GVolume("World", "Air", bbox_solid.name)
    gdml_model.add_volume(world_vol)

    if not top_cells:
        if has_universe:
            u0_cells = [c.cell_id for c in mcells if getattr(c, "universe", 0) == 0 and c.impn != 0]
            if not u0_cells:
                u0_cells = [c.cell_id for c in mcells if getattr(c, "universe", 0) == 0]
            top_cells = u0_cells
            print(f"[info] No --top-cells specified; defaulting to universe 0 cells ({len(top_cells)}).")
        else:
            top_cells = [c.cell_id for c in mcells]
            print(f"[info] No --top-cells specified; defaulting to all cells ({len(top_cells)}).")

    def _make_clip_intersection(first_name: str, second_name: str, tag: str, pos=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0)):
        posk = tuple(_round_key(v, 6) for v in pos)
        rotk = tuple(_round_key(v, 6) for v in rot)
        cache_key = (first_name, second_name, posk, rotk)
        inter_cache = ctx.setdefault("inter_cache", {})
        if cache_key in inter_cache:
            return inter_cache[cache_key]
        if posk == (0.0, 0.0, 0.0) and rotk == (0.0, 0.0, 0.0):
            rev_key = (second_name, first_name, posk, rotk)
            if rev_key in inter_cache:
                return inter_cache[rev_key]

        idx = ctx["bool_counter"]
        ctx["bool_counter"] += 1
        name = f"Clip_{tag}_{idx}"
        pos_vec = _make_vec(f"Pos_{name}", "position", "cm", pos)
        rot_vec = _make_vec(f"Rot_{name}", "rotation", "deg", rot)
        gsolid = GBooleanSolid(name, "intersection", first_name, second_name, pos_vec, rot_vec)
        gdml_model.add_solid(gsolid)
        if first_name in ctx["eval_solids"] and second_name in ctx["eval_solids"]:
            ctx["eval_solids"][name] = EvalBoolean(
                "intersection",
                ctx["eval_solids"][first_name],
                ctx["eval_solids"][second_name],
                pos,
                rot,
            )
        inter_cache[cache_key] = name
        return name

    expanded_items = []
    exp_counter = 0
    has_material_cells = any(cell.mat_id > 0 for cell in mcells)

    def _emit_volume(cell_id: int, solid_name: str):
        nonlocal exp_counter
        cell = cell_by_id.get(cell_id)
        if cell is None:
            return
        mat_id = cell.mat_id
        # Terminal MCNP void cells are already represented by the Geant4 World
        # material.  Emitting them again as sibling physical volumes creates
        # redundant graveyard/world-boundary overlaps.  Preserve all-void
        # geometry decks, where Air volumes are the only visible geometry.
        if not _should_emit_terminal_cell(cell, has_material_cells):
            return
        mat_name = material_name_by_cell_id.get(cell_id, f"M{mat_id:>08d}") if mat_id > 0 else "Air"
        vol_name = f"Vol_{cell_id}_{exp_counter}"
        exp_counter += 1
        gvol = GVolume(vol_name, mat_name, solid_name)
        gdml_model.add_volume(gvol)
        expanded_items.append((cell_id, vol_name))

    def _expand_fill_children(
        fill_u: int,
        clip_name: str,
        clip_bounds,
        path: tuple[int, ...],
        active_u: tuple[int, ...],
        pose=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ):
        if fill_u in active_u:
            print(f"[warn] Recursive FILL loop detected at path {path}, universe {fill_u}; using container geometry.")
            return False
        children = universes.get(fill_u, [])
        if not children:
            print(f"[warn] Fill universe {fill_u} not found; using container geometry.")
            return False
        emitted = False
        for ch in children:
            if ch.impn == 0:
                continue
            _expand_cell(ch.cell_id, clip_name, clip_bounds, path, active_u + (fill_u,), pose=pose)
            emitted = True
        return emitted

    def _expand_lattice(
        cell,
        base_name: str,
        base_bounds,
        container_name: str,
        container_bounds,
        path,
        active_u,
        origin_pose=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ):
        fs = getattr(cell, "fill", None)
        if fs is None:
            return False

        if base_bounds is None:
            pitch_vectors, base_center = _cell_lattice_vectors(cell)
            if len(pitch_vectors) < 2:
                print(f"[warn] Cell {cell.cell_id} LAT=1 but cannot derive lattice pitch from planar bounds; fallback.")
                return False
            if fs.ranges is None and fs.universe is not None:
                # An unbounded simple lattice has no explicit index range in
                # the deck.  Instantiate a conservative symmetric range large
                # enough to cover the world box; the container intersection
                # removes all elements outside the actual filled region.
                world_span = max(2.0 * bbox["hx"], 2.0 * bbox["hy"], 2.0 * bbox["hz"])
                axes = []
                for vector in pitch_vectors:
                    pitch = math.sqrt(sum(v * v for v in vector))
                    if container_bounds is not None and all(container_bounds.get(a) is not None for a in ("x", "y", "z")):
                        unit = tuple(v / pitch for v in vector)
                        projected_span = sum(
                            abs(unit[i]) * (container_bounds[a][1] - container_bounds[a][0])
                            for i, a in enumerate(("x", "y", "z"))
                        )
                        radius = int(math.ceil(0.5 * projected_span / pitch + 0.5))
                    else:
                        radius = int(math.ceil(world_span / max(pitch, 1e-12))) + 1
                    axes.append(list(range(-radius, radius + 1)))
                while len(axes) < 3:
                    axes.append([0])
                    pitch_vectors.append((0.0, 0.0, 0.0))
                ninst = len(axes[0]) * len(axes[1]) * len(axes[2])
                if ninst > max_lattice_instances:
                    active_dimension = sum(_norm3(v) > 1e-12 for v in pitch_vectors)
                    scale = (max_lattice_instances / ninst) ** (1.0 / max(1, active_dimension))
                    for i, values in enumerate(axes):
                        if len(values) > 1:
                            radius = max(1, int(((len(values) - 1) // 2) * scale))
                            axes[i] = list(range(-radius, radius + 1))
                (opos, orot) = origin_pose
                r_origin = _euler_deg_to_matrix_zyx(orot)
                rotated_center = _mat_vec_mul(r_origin, base_center)
                container_eval = ctx["eval_solids"].get(container_name)
                active_vectors = [v for v in pitch_vectors if _norm3(v) > 1e-12]
                emitted = False
                for iz in axes[2]:
                    for iy in axes[1]:
                        for ix in axes[0]:
                            delta = [0.0, 0.0, 0.0]
                            for coeff, vector in zip((ix, iy, iz), pitch_vectors):
                                for k in range(3):
                                    delta[k] += coeff * vector[k]
                            if not _is_zero_transform((0.0, 0.0, 0.0), orot):
                                delta = list(_mat_vec_mul(r_origin, tuple(delta)))
                            pos = tuple(opos[k] + delta[k] for k in range(3))
                            # Avoid emitting mathematically empty Boolean
                            # intersections.  Geant4 rejects such daughters
                            # while closing/voxelising the world geometry.
                            if container_eval is not None:
                                elem_center = tuple(pos[k] + rotated_center[k] for k in range(3))
                                sample_points = [elem_center]
                                for mask in range(1 << len(active_vectors)):
                                    local = list(base_center)
                                    for iv, vector in enumerate(active_vectors):
                                        sign = 1.0 if mask & (1 << iv) else -1.0
                                        for k in range(3):
                                            local[k] += sign * 0.49 * vector[k]
                                    rotated = _mat_vec_mul(r_origin, tuple(local))
                                    sample_points.append(tuple(opos[k] + delta[k] + rotated[k] for k in range(3)))
                                if not any(container_eval.contains(point, 1e-8) for point in sample_points):
                                    continue
                            elem_clip_name = _make_clip_intersection(
                                container_name,
                                base_name,
                                f"{cell.cell_id}_{ix}_{iy}_{iz}",
                                pos=pos,
                                rot=orot,
                            )
                            if fs.universe == getattr(cell, "universe", 0):
                                _emit_volume(cell.cell_id, elem_clip_name)
                                emitted = True
                                continue
                            fill_pose = (pos, orot)
                            if fs.transform:
                                fpos, frot = _parse_transform_from_raw(
                                    fs.transform, tr_map, is_star=fs.is_star
                                )
                                fill_pose = _compose_pose(pos, orot, fpos, frot)
                            ok = _expand_fill_children(
                                fs.universe,
                                elem_clip_name,
                                None,
                                path + (cell.cell_id, ix, iy, iz),
                                active_u,
                                pose=fill_pose,
                            )
                            emitted = emitted or ok
                return emitted
            if fs.ranges is None or fs.entries is None:
                print(f"[warn] Cell {cell.cell_id} LAT=1 has incomplete FILL data; fallback.")
                return False
            ranges = list(fs.ranges)
            if len(ranges) == 3 and len(pitch_vectors) == 2 and ranges[2] == (0, 0):
                pitch_vectors.append((0.0, 0.0, 0.0))
            if len(pitch_vectors) < len(ranges):
                print(f"[warn] Cell {cell.cell_id} LAT=1 has insufficient independent pitch vectors; fallback.")
                return False

            def _indices(pair):
                lo, hi = pair
                step = 1 if hi >= lo else -1
                return list(range(lo, hi + step, step))

            axes = [_indices(pair) for pair in ranges]
            if len(axes) == 2:
                axes.append([0])
            expected = len(axes[0]) * len(axes[1]) * len(axes[2])
            if len(fs.entries) < expected or expected > max_lattice_instances:
                print(f"[warn] Cell {cell.cell_id} indexed FILL size is inconsistent or exceeds the instance cap; fallback.")
                return False
            entries = list(fs.entries[:expected])
            transforms = list(fs.entry_transforms or (None,) * len(entries))
            (opos, orot) = origin_pose
            r_origin = _euler_deg_to_matrix_zyx(orot)
            emitted = False
            ient = 0
            for iz in axes[2]:
                for iy in axes[1]:
                    for ix in axes[0]:
                        coeffs = (ix, iy, iz)
                        delta = [0.0, 0.0, 0.0]
                        for coeff, vector in zip(coeffs, pitch_vectors):
                            for k in range(3):
                                delta[k] += coeff * vector[k]
                        if not _is_zero_transform((0.0, 0.0, 0.0), orot):
                            delta = list(_mat_vec_mul(r_origin, tuple(delta)))
                        pos = tuple(opos[k] + delta[k] for k in range(3))
                        elem_clip_name = _make_clip_intersection(
                            container_name, base_name, f"{cell.cell_id}_{ix}_{iy}_{iz}", pos=pos, rot=orot
                        )
                        fill_u = int(entries[ient])
                        entry_transform = transforms[ient] if ient < len(transforms) else None
                        ient += 1
                        if fill_u == 0:
                            continue
                        if fill_u == getattr(cell, "universe", 0):
                            _emit_volume(cell.cell_id, elem_clip_name)
                            emitted = True
                            continue
                        fill_pose = (pos, orot)
                        if entry_transform:
                            fpos, frot = _parse_transform_from_raw(entry_transform, tr_map, is_star=fs.is_star)
                            fill_pose = _compose_pose(pos, orot, fpos, frot)
                        ok = _expand_fill_children(
                            fill_u,
                            elem_clip_name,
                            None,
                            path + (cell.cell_id, ix, iy, iz),
                            active_u,
                            pose=fill_pose,
                        )
                        emitted = emitted or ok
            return emitted

        axis_order = ("x", "y", "z")
        periodic_axes = [ax for ax in axis_order if base_bounds.get(ax) is not None]
        if not periodic_axes:
            print(f"[warn] Cell {cell.cell_id} LAT=1 has no bounded axis; fallback.")
            return False

        idx_lists = {}
        pitch_by_axis = {}
        (ox, oy, oz), (orx, ory, orz) = origin_pose
        has_rot = not _is_zero_transform((0.0, 0.0, 0.0), (orx, ory, orz))
        r_origin = _euler_deg_to_matrix_zyx((orx, ory, orz))
        off_by_axis = {"x": ox, "y": oy, "z": oz}
        local_container_limits = None
        if has_rot and container_bounds is not None and all(container_bounds.get(a) is not None for a in axis_order):
            corners = []
            for x in container_bounds["x"]:
                for y in container_bounds["y"]:
                    for z in container_bounds["z"]:
                        world_delta = (x - ox, y - oy, z - oz)
                        # inverse of an orthogonal rotation is its transpose
                        corners.append(
                            tuple(sum(r_origin[j][i] * world_delta[j] for j in range(3)) for i in range(3))
                        )
            local_container_limits = {
                axis: (min(p[i] for p in corners), max(p[i] for p in corners))
                for i, axis in enumerate(axis_order)
            }

        for axis in axis_order:
            if axis in periodic_axes:
                lo0, hi0 = base_bounds[axis]
                pitch = hi0 - lo0
                if pitch <= 0.0:
                    return False
                pitch_by_axis[axis] = pitch
                cpair = (
                    local_container_limits.get(axis)
                    if local_container_limits is not None
                    else (None if container_bounds is None else container_bounds.get(axis))
                )
                if cpair is None:
                    idx_lists[axis] = [0]
                else:
                    clo, chi = cpair
                    c0 = 0.5 * (lo0 + hi0) + (0.0 if has_rot else off_by_axis[axis])
                    n0 = int(math.ceil((clo - c0) / pitch))
                    n1 = int(math.floor((chi - c0) / pitch))
                    if n1 < n0:
                        return True
                    idx_lists[axis] = list(range(n0, n1 + 1))
            else:
                idx_lists[axis] = [0]

        def _axis_indices(lo: int, hi: int):
            step = 1 if hi >= lo else -1
            return list(range(lo, hi + step, step))

        # Indexed FILL: explicit universe map over lattice indices.
        if fs.ranges is not None and fs.entries is not None:
            if len(fs.ranges) == 2:
                rx, ry = fs.ranges
                rz = (0, 0)
            elif len(fs.ranges) == 3:
                rx, ry, rz = fs.ranges
            else:
                print(f"[warn] Cell {cell.cell_id} has unsupported FILL range rank ({len(fs.ranges)}); fallback.")
                return False

            ix_vals = _axis_indices(rx[0], rx[1])
            iy_vals = _axis_indices(ry[0], ry[1])
            iz_vals = _axis_indices(rz[0], rz[1])
            expected = len(ix_vals) * len(iy_vals) * len(iz_vals)
            if expected <= 0:
                print(f"[warn] Cell {cell.cell_id} has empty indexed FILL ranges; fallback.")
                return False

            entries = list(fs.entries)
            if len(entries) < expected:
                print(
                    f"[warn] Cell {cell.cell_id} indexed FILL has {len(entries)} entries, "
                    f"expected {expected}; fallback."
                )
                return False
            if len(entries) > expected:
                print(
                    f"[warn] Cell {cell.cell_id} indexed FILL has extra entries "
                    f"({len(entries)} > {expected}); truncating extras."
                )
                entries = entries[:expected]

            if expected > max_lattice_instances:
                print(
                    f"[warn] Cell {cell.cell_id} indexed lattice instances {expected} exceed cap {max_lattice_instances}; "
                    f"fallback."
                )
                return False

            emitted = False
            ient = 0
            for iz in iz_vals:
                for iy in iy_vals:
                    for ix in ix_vals:
                        fill_u = int(entries[ient])
                        entry_transform = None
                        if fs.entry_transforms is not None and ient < len(fs.entry_transforms):
                            entry_transform = fs.entry_transforms[ient]
                        ient += 1

                        dx = ix * pitch_by_axis.get("x", 0.0)
                        dy = iy * pitch_by_axis.get("y", 0.0)
                        dz = iz * pitch_by_axis.get("z", 0.0)
                        if has_rot:
                            ddx, ddy, ddz = _mat_vec_mul(r_origin, (dx, dy, dz))
                            px, py, pz = ox + ddx, oy + ddy, oz + ddz
                            prot = (orx, ory, orz)
                            elem_clip_bounds = None
                        else:
                            px, py, pz = ox + dx, oy + dy, oz + dz
                            prot = (0.0, 0.0, 0.0)
                            elem_bounds = _translate_bounds(base_bounds, (px, py, pz))
                            elem_clip_bounds = _intersect_bounds(container_bounds, elem_bounds)
                            if elem_clip_bounds is None:
                                continue

                        elem_clip_name = _make_clip_intersection(
                            container_name,
                            base_name,
                            f"{cell.cell_id}_{ix}_{iy}_{iz}",
                            pos=(px, py, pz),
                            rot=prot,
                        )

                        # 0 means void/unfilled entry in many decks; skip emission.
                        if fill_u == 0:
                            continue
                        # If entry points to current cell universe, keep the lattice element itself.
                        if fill_u == getattr(cell, "universe", 0):
                            _emit_volume(cell.cell_id, elem_clip_name)
                            emitted = True
                            continue

                        fill_pose = ((px, py, pz), prot)
                        if entry_transform:
                            fpos, frot = _parse_transform_from_raw(
                                entry_transform, tr_map, is_star=fs.is_star
                            )
                            fill_pose = _compose_pose((px, py, pz), prot, fpos, frot)
                        ok = _expand_fill_children(
                            fill_u,
                            elem_clip_name,
                            elem_clip_bounds,
                            path + (cell.cell_id, ix, iy, iz),
                            active_u,
                            pose=fill_pose,
                        )
                        emitted = emitted or ok
            return emitted

        # Single-universe fill: periodic replication clipped by container.
        fill_u = getattr(cell, "fill_universe", None)
        if fill_u is None:
            return False
        ninst = len(idx_lists["x"]) * len(idx_lists["y"]) * len(idx_lists["z"])
        if ninst > max_lattice_instances:
            print(
                f"[warn] Cell {cell.cell_id} lattice instances {ninst} exceed cap {max_lattice_instances}; "
                f"using central instance only."
            )
            idx_lists = {"x": [0], "y": [0], "z": [0]}

        emitted = False
        for ix in idx_lists["x"]:
            for iy in idx_lists["y"]:
                for iz in idx_lists["z"]:
                    dx = ix * pitch_by_axis.get("x", 0.0)
                    dy = iy * pitch_by_axis.get("y", 0.0)
                    dz = iz * pitch_by_axis.get("z", 0.0)
                    if has_rot:
                        ddx, ddy, ddz = _mat_vec_mul(r_origin, (dx, dy, dz))
                        px, py, pz = ox + ddx, oy + ddy, oz + ddz
                        prot = (orx, ory, orz)
                        elem_clip_bounds = None
                    else:
                        px, py, pz = ox + dx, oy + dy, oz + dz
                        prot = (0.0, 0.0, 0.0)
                        elem_bounds = _translate_bounds(base_bounds, (px, py, pz))
                        elem_clip_bounds = _intersect_bounds(container_bounds, elem_bounds)
                        if elem_clip_bounds is None:
                            continue

                    elem_clip_name = _make_clip_intersection(
                        container_name,
                        base_name,
                        f"{cell.cell_id}_{ix}_{iy}_{iz}",
                        pos=(px, py, pz),
                        rot=prot,
                    )
                    ok = _expand_fill_children(
                        fill_u,
                        elem_clip_name,
                        elem_clip_bounds,
                        path + (cell.cell_id, ix, iy, iz),
                        active_u,
                        pose=_compose_pose(
                            (px, py, pz),
                            prot,
                            *_parse_transform_from_raw(fs.transform or "", tr_map, is_star=fs.is_star),
                        ),
                    )
                    emitted = emitted or ok
        return emitted

    def _expand_hex_lattice(
        cell,
        base_name: str,
        container_name: str,
        path,
        active_u,
        origin_pose=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ):
        """Expand an indexed MCNP LAT=2 hexagonal lattice.

        The supported form is an RHP fundamental cell with two in-plane index
        ranges and an optional singleton axial range.  Each filled universe is
        clipped by the parent container, so pins outside an assembly duct are
        naturally removed by the same Boolean construction used for LAT=1.
        """
        fs = getattr(cell, "fill", None)
        lattice_info = _cell_hex_lattice_vectors(cell)
        if fs is None or lattice_info is None or fs.ranges is None or fs.entries is None:
            print(f"[warn] Cell {cell.cell_id} LAT=2 requires an indexed FILL and an RHP fundamental cell; fallback.")
            return False
        vectors, base_center = lattice_info
        if len(fs.ranges) == 2:
            rx, ry = fs.ranges
            rz = (0, 0)
        elif len(fs.ranges) == 3 and fs.ranges[2] == (0, 0):
            rx, ry, rz = fs.ranges
        else:
            print(f"[warn] Cell {cell.cell_id} LAT=2 has unsupported index ranges {fs.ranges}; fallback.")
            return False

        def _indices(pair):
            lo, hi = pair
            return list(range(lo, hi + (1 if hi >= lo else -1), 1 if hi >= lo else -1))

        ix_vals, iy_vals, iz_vals = _indices(rx), _indices(ry), _indices(rz)
        expected = len(ix_vals) * len(iy_vals) * len(iz_vals)
        if expected <= 0 or len(fs.entries) < expected or expected > max_lattice_instances:
            print(f"[warn] Cell {cell.cell_id} LAT=2 indexed FILL size is inconsistent or exceeds the instance cap; fallback.")
            return False
        if len(fs.entries) > expected:
            print(f"[warn] Cell {cell.cell_id} LAT=2 indexed FILL has extra entries; truncating extras.")

        entries = list(fs.entries[:expected])
        transforms = list(fs.entry_transforms or (None,) * len(entries))
        (opos, orot) = origin_pose
        r_origin = _euler_deg_to_matrix_zyx(orot)
        container_eval = ctx["eval_solids"].get(container_name)
        emitted = False
        ient = 0
        for iz in iz_vals:
            for iy in iy_vals:
                for ix in ix_vals:
                    fill_u = int(entries[ient])
                    entry_transform = transforms[ient] if ient < len(transforms) else None
                    ient += 1
                    local_delta = tuple(
                        ix * vectors[0][k] + iy * vectors[1][k] for k in range(3)
                    )
                    delta = _mat_vec_mul(r_origin, local_delta)
                    pos = tuple(opos[k] + delta[k] for k in range(3))
                    # Indexed hex maps commonly include blank cells around the
                    # assembly perimeter.  A cell whose centre is outside the
                    # parent duct is fully removed by the mathematical clip,
                    # but Geant4 rejects it during voxel construction before
                    # evaluating that Boolean intersection.
                    rotated_center = _mat_vec_mul(r_origin, base_center)
                    sample_point = tuple(pos[k] + rotated_center[k] for k in range(3))
                    if container_eval is not None and not container_eval.contains(sample_point, 1e-8):
                        continue
                    elem_clip_name = _make_clip_intersection(
                        container_name, base_name, f"{cell.cell_id}_{ix}_{iy}_{iz}", pos=pos, rot=orot
                    )
                    if fill_u == 0:
                        continue
                    if fill_u == getattr(cell, "universe", 0):
                        _emit_volume(cell.cell_id, elem_clip_name)
                        emitted = True
                        continue
                    fill_pose = (pos, orot)
                    if entry_transform:
                        fpos, frot = _parse_transform_from_raw(
                            entry_transform, tr_map, is_star=fs.is_star
                        )
                        fill_pose = _compose_pose(pos, orot, fpos, frot)
                    emitted = _expand_fill_children(
                        fill_u,
                        elem_clip_name,
                        None,
                        path + (cell.cell_id, ix, iy, iz),
                        active_u,
                        pose=fill_pose,
                    ) or emitted
        return emitted

    def _expand_cell(
        cell_id: int,
        clip_name: str | None,
        clip_bounds,
        path: tuple[int, ...],
        active_u: tuple[int, ...],
        pose=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ):
        nonlocal exp_counter
        cell = cell_by_id.get(cell_id)
        if cell is None:
            return

        base_name = cell_roots.get(cell_id)
        if base_name is None:
            return
        base_bounds = cell_bounds.get(cell_id)
        tr_pos, tr_rot = _cell_trcl_pose(cell)
        local_offset, local_rot = _compose_pose(pose[0], pose[1], tr_pos, tr_rot)
        shifted_base_bounds = _translate_bounds(base_bounds, local_offset)
        if not _is_zero_transform((0.0, 0.0, 0.0), local_rot):
            shifted_base_bounds = None

        if clip_name is None:
            if _is_zero_transform(local_offset, local_rot):
                solid_name = base_name
            else:
                solid_name = _make_clip_intersection(
                    ctx["bbox_name"],
                    base_name,
                    f"{cell_id}_off",
                    pos=local_offset,
                    rot=local_rot,
                )
            solid_bounds = shifted_base_bounds
        else:
            solid_name = _make_clip_intersection(
                clip_name, base_name, f"{cell_id}", pos=local_offset, rot=local_rot
            )
            if clip_bounds is None:
                solid_bounds = shifted_base_bounds
            else:
                solid_bounds = _intersect_bounds(clip_bounds, shifted_base_bounds)
                if shifted_base_bounds is not None and solid_bounds is None:
                    return

        fs = getattr(cell, "fill", None)
        fill_u = getattr(cell, "fill_universe", None)
        if fs is not None and _fill_supported(cell) and getattr(cell, "lat", 0) == 1:
            if clip_name is None:
                container_name = solid_name
                container_bounds = solid_bounds
            else:
                container_name = clip_name
                container_bounds = clip_bounds
                if container_bounds is None:
                    container_bounds = solid_bounds
            if _expand_lattice(
                cell,
                base_name,
                base_bounds,
                container_name,
                container_bounds,
                path,
                active_u,
                origin_pose=(local_offset, local_rot),
            ):
                return

        if fs is not None and _fill_supported(cell) and getattr(cell, "lat", 0) == 2:
            container_name = solid_name if clip_name is None else clip_name
            if _expand_hex_lattice(
                cell,
                base_name,
                container_name,
                path,
                active_u,
                origin_pose=(local_offset, local_rot),
            ):
                return

        if fs is not None and _fill_supported(cell) and fill_u is not None:
            fill_pose = (local_offset, local_rot)
            if fs.transform:
                fpos, frot = _parse_transform_from_raw(fs.transform, tr_map, is_star=fs.is_star)
                fill_pose = _compose_pose(local_offset, local_rot, fpos, frot)
            if _expand_fill_children(
                fill_u, solid_name, solid_bounds, path + (cell_id,), active_u, pose=fill_pose
            ):
                return

        _emit_volume(cell_id, solid_name)

    for cid in top_cells:
        if cid not in cell_roots:
            print(f"[warn] Top cell {cid} not found; skipping placement.")
            continue
        _expand_cell(
            cid, None, cell_bounds.get(cid), tuple(), tuple(), pose=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        )

    for cell_id, vol_name in expanded_items:
        if not cell_template_enabled.get(cell_id, False):
            pos_name = "center"
            rot_name = "identity"
        else:
            pos, rot = cell_place.get(cell_id, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
            if pos != (0.0, 0.0, 0.0):
                pos_name = f"Pos_Cell_{cell_id}"
                if pos_name not in define_cache:
                    gdml_model.add_define(GVector(pos_name, "position", "cm", x=pos[0], y=pos[1], z=pos[2]))
                    define_cache[pos_name] = pos
            else:
                pos_name = "center"

            if rot != (0.0, 0.0, 0.0):
                rot_name = f"Rot_Cell_{cell_id}"
                if rot_name not in define_cache:
                    gdml_model.add_define(GVector(rot_name, "rotation", "deg", x=rot[0], y=rot[1], z=rot[2]))
                    define_cache[rot_name] = rot
            else:
                rot_name = "identity"
        phys = GPhysicalVolume(f"Phys_{vol_name}", vol_name, pos_name, rot_name)
        world_vol.add_physvol(phys)

    if validate and any(
        int(validate.get(name, 0)) > 0 for name in ("samples", "local_samples", "boundary_samples")
    ):
        if validate.get("cells") is None and top_cells:
            validate["cells"] = top_cells
        _run_validation(mcnp_model, cell_roots, cell_place, ctx, validate)

    if dump_geom:
        dump_path = dump_geom if isinstance(dump_geom, str) else None
        if dump_path is None:
            dump_path = "geom_dump.json"
        with open(dump_path, "w", encoding="utf-8") as f:
            json.dump(geom_dump, f, indent=2)
        print(f"[info] Geometry AST dumped to {dump_path}")

    if return_debug:
        return {
            "bbox": bbox,
            "cell_roots": cell_roots,
            "cell_place": cell_place,
            "eval_solids": ctx["eval_solids"],
            "top_cells": list(top_cells),
        }
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert MCNP input to GDML.")
    parser.add_argument("inp_file", help="MCNP input file")
    parser.add_argument("out_file", help="Output GDML file")
    parser.add_argument("--top-cells", default="", help="Comma-separated top cell ids to place into world")
    parser.add_argument("--bbox", default="", help="Override bbox: x0,x1,y0,y1,z0,z1")
    parser.add_argument("--bbox-margin", type=float, default=0.1, help="BBox expansion margin (ratio)")
    parser.add_argument("--dump-geom", nargs="?", const=True, default=False, help="Dump geometry AST to JSON (optional path)")
    parser.add_argument(
        "--write-manifest",
        default="",
        help="Write conversion metadata JSON, including the MCNP-to-GDML coordinate translation",
    )
    parser.add_argument("--log", action="store_true", help="Enable debug logs for expression normalization and templates")
    parser.add_argument("--validate", type=int, default=0, help="Validate geometry with N random samples per cell")
    parser.add_argument("--validate-local", type=int, default=0, help="Validate with N cell-local samples per cell")
    parser.add_argument(
        "--validate-boundary",
        type=int,
        default=0,
        help="Generate N near-boundary point pairs per supported surface",
    )
    parser.add_argument(
        "--validate-boundary-delta",
        type=float,
        default=0.0,
        help="Offset from each analytic boundary in cm (default: scale-aware)",
    )
    parser.add_argument("--validate-cells", default="", help="Comma-separated cell ids to validate (default: top cells)")
    parser.add_argument("--validate-seed", type=int, default=0, help="Random seed for validation sampling")
    parser.add_argument("--validate-eps", type=float, default=1e-6, help="Epsilon for inside/outside checks")
    parser.add_argument("--validate-out", default="", help="Write validation report JSON to this path")
    parser.add_argument(
        "--validate-g4-points",
        default="",
        help="Write tab-separated solid-local point queries for independent Geant4 Inside() checks",
    )

    args = parser.parse_args()

    in_fpath = args.inp_file
    out_fpath = args.out_file

    top_cells = _parse_top_cells(args.top_cells) if args.top_cells else []
    bbox_override = _parse_bbox(args.bbox) if args.bbox else None
    validate_cells = _parse_top_cells(args.validate_cells) if args.validate_cells else []

    mcnp_model = MModel()
    mcnp_model.read_from_file(in_fpath)

    gdml_model = GModel()
    validate = None
    if args.validate > 0 or args.validate_local > 0 or args.validate_boundary > 0:
        validate = {
            "samples": args.validate,
            "local_samples": args.validate_local,
            "boundary_samples": args.validate_boundary,
            "seed": args.validate_seed,
            "eps": args.validate_eps,
            "cells": validate_cells if validate_cells else None,
            "out_path": args.validate_out if args.validate_out else None,
            "geant4_points_out": args.validate_g4_points if args.validate_g4_points else None,
        }
        if args.validate_boundary_delta > 0.0:
            validate["boundary_delta"] = args.validate_boundary_delta
    debug = mcnp2Gdml(
        mcnp_model,
        gdml_model,
        top_cells,
        bbox_override,
        args.bbox_margin,
        args.dump_geom,
        args.log,
        validate,
        return_debug=bool(args.write_manifest),
    )
    os.makedirs(os.path.dirname(out_fpath) or ".", exist_ok=True)
    gdml_model.write_gdml(out_fpath)
    if args.write_manifest:
        bbox = debug["bbox"]
        translation = bbox["shift"]
        transport_boundaries = []
        for surface in mcnp_model.surfaces:
            if not surface.boundary:
                continue
            transport_boundaries.append({
                "surface_id": surface.sid,
                "surface_type": surface.stype.value,
                "parameters_mcnp_cm": list(surface.params),
                "transform_id": surface.transform_id,
                "mcnp_boundary": {
                    "*": "reflecting",
                    "+": "white",
                }.get(surface.boundary, "other"),
                "gdml_transport_status": "not encoded; reproduce separately before transport comparison",
            })
        manifest = {
            "schema_version": 2,
            "input": os.path.abspath(in_fpath),
            "output": os.path.abspath(out_fpath),
            "top_cells": debug["top_cells"],
            "world_bbox_mcnp_cm": {
                "center": [bbox["cx"], bbox["cy"], bbox["cz"]],
                "half_lengths": [bbox["hx"], bbox["hy"], bbox["hz"]],
            },
            "coordinate_transform": {
                "from": "MCNP cm",
                "to": "GDML cm",
                "operation": "translation",
                "translation_cm": list(translation),
                "formula": "p_gdml_cm = p_mcnp_cm + translation_cm",
            },
            "transport_boundary_conditions": {
                "count": len(transport_boundaries),
                "surfaces": transport_boundaries,
                "note": "GDML represents geometry only; MCNP reflecting and white boundary semantics require a separately qualified transport implementation.",
            },
        }
        os.makedirs(os.path.dirname(args.write_manifest) or ".", exist_ok=True)
        with open(args.write_manifest, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"[info] Conversion manifest written to {args.write_manifest}")
