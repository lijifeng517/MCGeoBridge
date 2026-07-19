
import xml.etree.ElementTree as ET
import re
import math


from .MCell import MCell
from .MMaterial import MMaterial
from .MSurface  import MSurface
from .MUtil import str2float
from .MExprParser import decode_facet_id


class MModel():
    _instance = None

    def __new__(cls):
        if cls._instance == None:
            cls._instance = super().__new__(cls)
            cls._instance._reset_data()
            
        return cls._instance

    def _reset_data(self):
        self._name = ''
        self._surfaces = []
        self._cells = []
        self._materials = []
        self._universes = {}
        self._transforms = {}


    def read_from_file(self, inp: str):
        # Important for GUI multi-load: clear previous model content first.
        self._reset_data()
        blocks  = []
        cur_blk = []
        with open(inp, 'r') as inpFl:
            flag_continue = False
            lines = inpFl.readlines()
            if not lines:
                return
            # ``MESSAGE: CONTINUE`` is a legal MCNP preamble for decks without
            # a conventional title card.  It is neither a cell nor a surface
            # card and must be removed before the three-card-block split.
            start_line = 1
            if lines[0].strip().upper().startswith("MESSAGE:"):
                self.set_name(inp)
                start_line = 1
                while start_line < len(lines) and (
                    not lines[start_line].strip()
                    or lines[start_line].strip().upper() == "CONTINUE"
                ):
                    start_line += 1
            else:
                self.set_name(lines[0])
            for line in lines[start_line:]:
                line = line.upper()
                regular_line = line.rstrip()
                # blank lines as delimieters
                if regular_line == '':
                    blocks.append(cur_blk)
                    cur_blk = []
                    continue
                
                 # comment information 
                idx_dollar = regular_line.find('$')
                if idx_dollar >= 0:
                    regular_line = regular_line[:idx_dollar]
                if regular_line.strip() == "":
                    continue

                first_5char = line[0:5]
                lstr = regular_line.lstrip()
                # comment line (first non-space 'C')
                if lstr.startswith('C') and (len(lstr) == 1 or lstr[1].isspace()):
                    continue

                # continuation from previous trailing '&' line
                if flag_continue and cur_blk:
                    flag_continue = False
                    if regular_line.endswith('&'):
                        flag_continue = True
                        regular_line = regular_line[:-1]
                    cur_blk[-1] = (cur_blk[-1] + " " + regular_line.strip()).strip()
                    continue

                # continuation on the previous line (traditional 5-space indent)
                if (first_5char == ' '*5 or line.startswith('\t')) and cur_blk:
                    cur_blk[-1] = (cur_blk[-1] + " " + regular_line.strip()).strip()
                    continue
                # data continue on the following line
                if regular_line[-1] == '&':
                    flag_continue = True 
                    regular_line = regular_line[:-1]
                    cur_blk.append(regular_line)
                    continue
               
                cur_blk.append(regular_line)
            

            # append the last block
            if len(cur_blk) != 0:
                blocks.append(cur_blk) 

            

            nblocks = len(blocks)
            blk_cells = blocks[0] if nblocks > 0 else []
            blk_surfs = blocks[1] if nblocks > 1 else []
            blk_data = blocks[2] if nblocks > 2 else []

            cell_index = {}
            for line in blk_cells:
                fields = line.split()
                if not fields:
                    continue
                if len(fields) >= 4 and fields[1] == "LIKE":
                    new_id = int(fields[0])
                    ref_id = int(fields[2])
                    ref_cell = cell_index.get(ref_id)
                    if ref_cell is None:
                        raise ValueError(f"LIKE cell reference {ref_id} not found for line: '{line}'")

                    key_opts = dict(ref_cell.key_opts)
                    if "BUT" in fields:
                        ibut = fields.index("BUT")
                        but_opts = self._parse_key_opts(fields[ibut + 1 :])
                        key_opts.update(but_opts)

                    cell = MCell(new_id, ref_cell.mat_id, ref_cell.density, ref_cell.raw_geom_expr, key_opts, ref_cell.raw_geom_expr)
                else:
                    # Skip non-cell lines accidentally captured in this block.
                    if not fields[0].lstrip("+-").isdigit():
                        continue
                    cell = MCell.create_from_str(line)

                self.add_cell(cell)
                cell_index[cell.cell_id] = cell



            for line in blk_surfs:
                surf = MSurface.create_from_str(line)
                self.add_surface(surf)


            for line in blk_data:
                fields = line.split()
                if not fields:
                    continue
                keyword = fields[0]
                if keyword[0] == 'M' and keyword[1:].isdigit():
                    material = MMaterial.create_from_str(line)
                    self.add_material(material)
                elif keyword == 'IMP:N':
                    impn_vals = self._expand_numeric_card(fields[1:])
                    for icell, cell in enumerate(self._cells):
                        if icell < len(impn_vals):
                            cell.impn = impn_vals[icell]
                elif (keyword.startswith("TR") and keyword[2:].isdigit()) or (
                    keyword.startswith("*TR") and keyword[3:].isdigit()
                ):
                    tid = int(keyword[2:] if keyword.startswith("TR") else keyword[3:])
                    is_star = keyword.startswith("*TR")
                    vals = []
                    for fv in fields[1:]:
                        try:
                            vals.append(str2float(fv))
                        except Exception:
                            pass
                    tdef = self._parse_transform_vals(vals, is_star=is_star)
                    if tdef is not None:
                        self._transforms[tid] = tdef


            self._apply_surface_transforms()
            self._expand_macrobody_facets()


            # get the associated surfaces with this cell
            for cell in self._cells:
                surf_ids = cell.surf_ids
                surfaces = []
                for surf_id in surf_ids:
                    for surf in self._surfaces:
                        if surf.sid == surf_id:
                            surfaces.append(surf)
                cell.surfaces = surfaces

                cell.update_geometry_AST()

            self._build_universe_index()


    @staticmethod
    def _parse_key_opts(tokens):
        key_opts = {}
        active_key = None
        for field in tokens:
            if '=' in field:
                key, val = field.split('=', 1)
                active_key = key.upper()
                key_opts[active_key] = val
            elif active_key is not None:
                key_opts[active_key] = (key_opts.get(active_key, "") + " " + field).strip()
        return key_opts

    @staticmethod
    def _expand_numeric_card(tokens):
        """Expand numeric data-card values with MCNP nR and nI notation."""
        values = []
        i = 0
        while i < len(tokens):
            token = tokens[i].upper()
            if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[ED][+-]?\d+)?", token):
                values.append(str2float(token))
            elif re.fullmatch(r"\d+R", token) and values:
                values.extend([values[-1]] * int(token[:-1]))
            elif re.fullmatch(r"\d+I", token) and values and i + 1 < len(tokens):
                count = int(token[:-1])
                try:
                    end = str2float(tokens[i + 1])
                except Exception:
                    i += 1
                    continue
                start = values[-1]
                step = (end - start) / (count + 1)
                values.extend(start + step * j for j in range(1, count + 1))
            i += 1
        return values


    def _build_universe_index(self):
        self._universes = {}
        for cell in self._cells:
            uid = getattr(cell, "universe", 0)
            if uid not in self._universes:
                self._universes[uid] = []
            self._universes[uid].append(cell)

    @staticmethod
    def _matrix_to_euler_deg_zyx(m):
        # R = Rz(rz)*Ry(ry)*Rx(rx)
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

    @classmethod
    def _parse_transform_vals(cls, vals, is_star=False):
        if len(vals) < 3:
            return None

        pos = (vals[0], vals[1], vals[2])
        rot = (0.0, 0.0, 0.0)

        if len(vals) >= 12:
            ang = vals[3:12]
            if is_star:
                # *TR supplies the nine direction angles in degrees. Convert
                # each one to its direction cosine before building the matrix.
                ang = [math.cos(math.radians(v)) for v in ang]
            # Direction-cosine matrix (x', y', z' local axes in global coords).
            b1, b2, b3, b4, b5, b6, b7, b8, b9 = ang
            m = [
                [b1, b4, b7],
                [b2, b5, b8],
                [b3, b6, b9],
            ]
            rot = cls._matrix_to_euler_deg_zyx(m)
        elif len(vals) >= 6:
            # Pragmatic support: translation + XYZ Euler (degrees).
            rot = (vals[3], vals[4], vals[5])

        return {"pos": pos, "rot": rot}

    @staticmethod
    def _euler_matrix_zyx(rot):
        rx, ry, rz = [math.radians(float(v)) for v in rot]
        cx, sx = math.cos(rx), math.sin(rx)
        cy, sy = math.cos(ry), math.sin(ry)
        cz, sz = math.cos(rz), math.sin(rz)
        return [
            [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
            [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
            [-sy, cy * sx, cy * cx],
        ]

    @staticmethod
    def _mat_vec(m, v):
        return (
            m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
        )

    @classmethod
    def _surface_to_global(cls, surf, transform):
        """Return a canonical global-coordinate surface for a rigid TR card."""
        from .MSurface import MSurfType

        pos = tuple(transform.get("pos", (0.0, 0.0, 0.0)))
        matrix = cls._euler_matrix_zyx(transform.get("rot", (0.0, 0.0, 0.0)))

        def point(p):
            rp = cls._mat_vec(matrix, p)
            return (rp[0] + pos[0], rp[1] + pos[1], rp[2] + pos[2])

        def vector(v):
            return cls._mat_vec(matrix, v)

        stype = surf.stype
        p = surf.params
        out_type = stype
        out = list(p)

        if stype in (MSurfType.P, MSurfType.PX, MSurfType.PY, MSurfType.PZ):
            if stype == MSurfType.P:
                normal, offset = tuple(p[0:3]), p[3]
            elif stype == MSurfType.PX:
                normal, offset = (1.0, 0.0, 0.0), p[0]
            elif stype == MSurfType.PY:
                normal, offset = (0.0, 1.0, 0.0), p[0]
            else:
                normal, offset = (0.0, 0.0, 1.0), p[0]
            n = vector(normal)
            out_type = MSurfType.P
            out = [n[0], n[1], n[2], offset + n[0] * pos[0] + n[1] * pos[1] + n[2] * pos[2]]
        elif stype in (MSurfType.SO, MSurfType.SPH):
            if stype == MSurfType.SO:
                center, radius = (0.0, 0.0, 0.0), p[0]
            elif len(p) >= 4:
                center, radius = tuple(p[0:3]), p[3]
            else:
                center, radius = (0.0, 0.0, 0.0), p[0]
            c = point(center)
            out_type = MSurfType.SPH
            out = [c[0], c[1], c[2], radius]
        elif stype in (MSurfType.CX, MSurfType.CY, MSurfType.CZ,
                       MSurfType.C_X, MSurfType.C_Y, MSurfType.C_Z):
            if stype == MSurfType.CX:
                base, axis, radius = (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), p[0]
            elif stype == MSurfType.CY:
                base, axis, radius = (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), p[0]
            elif stype == MSurfType.CZ:
                base, axis, radius = (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), p[0]
            elif stype == MSurfType.C_X:
                base, axis, radius = (0.0, p[0], p[1]), (1.0, 0.0, 0.0), p[2]
            elif stype == MSurfType.C_Y:
                base, axis, radius = (p[0], 0.0, p[1]), (0.0, 1.0, 0.0), p[2]
            else:
                base, axis, radius = (p[0], p[1], 0.0), (0.0, 0.0, 1.0), p[2]
            b = point(base)
            a = vector(axis)
            out_type = MSurfType.C_G
            out = [b[0], b[1], b[2], a[0], a[1], a[2], radius]
        elif stype == MSurfType.RPP:
            x0, x1, y0, y1, z0, z1 = p[0:6]
            base = point((min(x0, x1), min(y0, y1), min(z0, z1)))
            a = vector((abs(x1 - x0), 0.0, 0.0))
            b = vector((0.0, abs(y1 - y0), 0.0))
            c = vector((0.0, 0.0, abs(z1 - z0)))
            out_type = MSurfType.BOX
            out = [*base, *a, *b, *c]
        elif stype == MSurfType.RCC:
            base = point(tuple(p[0:3]))
            h = vector(tuple(p[3:6]))
            out = [*base, *h, p[6]]
        elif stype == MSurfType.TRC:
            base = point(tuple(p[0:3]))
            h = vector(tuple(p[3:6]))
            out = [*base, *h, p[6], p[7]]
        elif stype == MSurfType.RHP:
            base = point(tuple(p[0:3]))
            h = vector(tuple(p[3:6]))
            u = vector(tuple(p[6:9]))
            out = [*base, *h, *u]
        elif stype == MSurfType.ELL_G:
            center = point(tuple(p[0:3]))
            e1 = vector(tuple(p[3:6]))
            e2 = vector(tuple(p[6:9]))
            e3 = vector(tuple(p[9:12]))
            out = [*center, *e1, *e2, *e3, *p[12:15]]
        elif stype == MSurfType.SQ and len(p) >= 10:
            a, b, c, d, e, f, g, x0, y0, z0 = p[0:10]
            coeffs = (a, b, c)
            zeros = [abs(value) <= 1e-12 for value in coeffs]
            if (
                any(abs(value) > 1e-12 for value in (d, e, f))
                or g >= 0.0
                or sum(zeros) != 1
                or any(value <= 0.0 for value, zero in zip(coeffs, zeros) if not zero)
            ):
                return surf
            local_axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            nonzero = [index for index, zero in enumerate(zeros) if not zero]
            axis_index = zeros.index(True)
            center = point((x0, y0, z0))
            e1 = vector(local_axes[nonzero[0]])
            e2 = vector(local_axes[nonzero[1]])
            axis = vector(local_axes[axis_index])
            r1 = math.sqrt(-g / coeffs[nonzero[0]])
            r2 = math.sqrt(-g / coeffs[nonzero[1]])
            out_type = MSurfType.ECYL_G
            out = [*center, *e1, *e2, *axis, r1, r2]
        else:
            return surf

        return MSurface(surf.sid, out_type, out, None, surf.boundary)

    def _apply_surface_transforms(self):
        transformed = []
        for surf in self._surfaces:
            tid = getattr(surf, "transform_id", None)
            if tid is None:
                transformed.append(surf)
                continue
            transform = self._transforms.get(tid)
            if transform is None:
                transformed.append(surf)
                continue
            transformed.append(self._surface_to_global(surf, transform))
        self._surfaces = transformed

    @staticmethod
    def _dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    @staticmethod
    def _cross(a, b):
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    @classmethod
    def _unit(cls, value):
        length = math.sqrt(cls._dot(value, value))
        if length <= 1e-15:
            raise ValueError(f"Cannot construct macrobody facet from zero vector {value}")
        return tuple(component / length for component in value)

    @classmethod
    def _plane_surface(cls, sid, normal, point):
        from .MSurface import MSurfType
        n = cls._unit(normal)
        return MSurface(sid, MSurfType.P, [*n, cls._dot(n, point)])

    @classmethod
    def _macrobody_facet(cls, base, facet, synthetic_sid):
        from .MSurface import MSurfType

        p = base.params
        if base.stype == MSurfType.RPP and 1 <= facet <= 6:
            x0, x1, y0, y1, z0, z1 = p[0:6]
            planes = {
                1: ((-1, 0, 0), (min(x0, x1), 0, 0)),
                2: ((1, 0, 0), (max(x0, x1), 0, 0)),
                3: ((0, -1, 0), (0, min(y0, y1), 0)),
                4: ((0, 1, 0), (0, max(y0, y1), 0)),
                5: ((0, 0, -1), (0, 0, min(z0, z1))),
                6: ((0, 0, 1), (0, 0, max(z0, z1))),
            }
            return cls._plane_surface(synthetic_sid, *planes[facet])

        if base.stype == MSurfType.BOX and 1 <= facet <= 6:
            origin = tuple(p[0:3])
            a, b, c = tuple(p[3:6]), tuple(p[6:9]), tuple(p[9:12])
            data = {
                1: (tuple(-v for v in a), origin),
                2: (a, tuple(origin[i] + a[i] for i in range(3))),
                3: (tuple(-v for v in b), origin),
                4: (b, tuple(origin[i] + b[i] for i in range(3))),
                5: (tuple(-v for v in c), origin),
                6: (c, tuple(origin[i] + c[i] for i in range(3))),
            }
            return cls._plane_surface(synthetic_sid, *data[facet])

        if base.stype == MSurfType.RCC and 1 <= facet <= 3:
            origin = tuple(p[0:3])
            h = tuple(p[3:6])
            if facet == 1:
                axis = cls._unit(h)
                return MSurface(synthetic_sid, MSurfType.C_G, [*origin, *axis, p[6]])
            if facet == 2:
                return cls._plane_surface(synthetic_sid, tuple(-v for v in h), origin)
            top = tuple(origin[i] + h[i] for i in range(3))
            return cls._plane_surface(synthetic_sid, h, top)
        if base.stype == MSurfType.TRC and 1 <= facet <= 3:
            origin = tuple(p[0:3])
            h = tuple(p[3:6])
            if facet == 1:
                return MSurface(synthetic_sid, MSurfType.TRC, list(p[0:8]))
            if facet == 2:
                return cls._plane_surface(synthetic_sid, tuple(-v for v in h), origin)
            top = tuple(origin[i] + h[i] for i in range(3))
            return cls._plane_surface(synthetic_sid, h, top)
        return None

    def _expand_macrobody_facets(self):
        surface_by_id = {surface.sid: surface for surface in self._surfaces}
        requested = set()
        for cell in self._cells:
            for sid in cell.surf_ids:
                decoded = decode_facet_id(sid)
                if decoded is not None:
                    requested.add((sid, decoded[0], decoded[1]))
        for synthetic_sid, base_sid, facet in sorted(requested):
            base = surface_by_id.get(base_sid)
            if base is None:
                continue
            generated = self._macrobody_facet(base, facet, synthetic_sid)
            if generated is not None:
                self._surfaces.append(generated)
                surface_by_id[synthetic_sid] = generated





    def set_name(self, name: str):
        self._name = name



    def add_surface(self, mSurface: MSurface):
        if not isinstance(mSurface, MSurface):
            raise TypeError("Error! A MSurface type expected in function MModel:add_surface.")
        self._surfaces.append(mSurface)



    def add_cell(self, mCell: MCell):
        if not isinstance(mCell, MCell):
            raise TypeError("Error! A MCell type expected in function MModel:add_cell.")
        self._cells.append(mCell)



    def add_material(self, mMaterial: MMaterial):
        if not isinstance(mMaterial, MMaterial):
            raise TypeError("Error! A MMaterial type expected in function MModel:add_material.")
        self._materials.append(mMaterial)





    @property
    def name(self):
        return self._name



    @property
    def surfaces(self):
        return self._surfaces



    @property
    def cells(self):
        return self._cells



    @property
    def materials(self):
        return self._materials

    @property
    def universes(self):
        return self._universes

    @property
    def transforms(self):
        return self._transforms
