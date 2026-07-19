
from __future__ import annotations
import re
from dataclasses import dataclass

from .MUtil import str2float
from .MExprParser import parse_geom_expr, collect_surface_ids
from .MSurface import MSurface



PAT_UNION = r"""
        ^
        \(?                     # 左括号
        (
        [+-]?\d+                # 第一个数字（可能带符号）
        (?:[:]+[+-]?\d+)*       # 后续数字（允许冒号分隔）
        )
        \)?                     # 右括号
        $
    """


_KNOWN_CELL_KEYS = {
    "IMP:N",
    "U",
    "LAT",
    "FILL",
    "TRCL",
    "LIKE",
    "BUT",
}


@dataclass(frozen=True)
class MFillSpec:
    raw: str
    universe: int | None
    ranges: tuple[tuple[int, int], ...] | None = None
    entries: tuple[int, ...] | None = None
    transform: str | None = None
    entry_transforms: tuple[str | None, ...] | None = None
    is_star: bool = False


class MCell:
    def __init__(self, cell_id: int, mat_id: int, 
                       dens: float, 
                       geom_expr: str, 
                       key_opts: map,
                       raw_geom_expr: str = None):
        self._cell_id   = cell_id
        self._mat_id    = mat_id
        self._density   = dens
        self._geom_expr = geom_expr
        self._raw_geom_expr = raw_geom_expr if raw_geom_expr is not None else geom_expr
        self._geom_AST  = None

        self._key_opts = {str(k).upper(): str(v).strip() for k, v in key_opts.items()}
        self._impn = self._parse_impn(self._key_opts)
        self._universe = int(self._key_opts.get("U", 0))
        self._lat = int(self._key_opts.get("LAT", 0)) if self._key_opts.get("LAT", "").strip() else 0
        self._fill = self._parse_fill(
            self._key_opts.get("FILL", ""),
            is_star=self._key_opts.get("FILL_STAR", "0") == "1",
        )
        self._surfaces  = []
        self._surf_ids  = []

        self._process_geom_expr()



    @classmethod
    def create_from_str(cls, data_str: str):
        fields = data_str.split()
        cell_id = int(fields[0])
        # Some CAD exporters write a void material id as ``0.00000``.
        # Accept integral float spelling while rejecting non-integral ids.
        mat_value = float(fields[1])
        if not mat_value.is_integer():
            raise ValueError(f"Non-integral material id '{fields[1]}' in cell line: '{data_str}'")
        mat_id = int(mat_value)
        dens = str2float(fields[2]) if mat_id > 0 else 0.0
        
        key_opts = {}
        geom_fields = []
        bgn_idx = 3 if mat_id > 0 else 2
        active_key = None
        option_fields = fields[bgn_idx:]
        i = 0
        while i < len(option_fields):
            field = option_fields[i]
            if '=' in field:
                key, val = field.split('=', 1)
                key_u = key.upper().lstrip("*")
                # Accept generic card-style key=value options (e.g. VOL=, TMP=, IMP:N,P=).
                if re.fullmatch(r"[A-Z][A-Z0-9:,_\-\*]*", key_u):
                    active_key = key_u
                    key_opts[active_key] = val
                    if key.startswith("*") and key_u == "FILL":
                        key_opts["FILL_STAR"] = "1"
                else:
                    active_key = None
                    geom_fields.append(field)
            elif (
                re.fullmatch(r"\*?[A-Z][A-Z0-9:,_\-\*]*", field.upper())
                and i + 1 < len(option_fields)
                and (option_fields[i + 1] == "=" or option_fields[i + 1].startswith("="))
            ):
                # MCNP writers commonly emit ``TRCL =7`` or ``VOL = 1``.
                # Treat the standalone keyword as a new option instead of
                # appending it to the preceding option value.
                active_key = field.upper().lstrip("*")
                nxt = option_fields[i + 1]
                if nxt == "=":
                    i += 1
                    val = ""
                else:
                    i += 1
                    val = nxt[1:]
                key_opts[active_key] = val
                if field.startswith("*") and active_key == "FILL":
                    key_opts["FILL_STAR"] = "1"
            elif field.upper().lstrip("*") in _KNOWN_CELL_KEYS and i + 1 < len(option_fields):
                # Some writers emit ``u 3`` or ``lat 1`` without an equals
                # sign. These keywords cannot be part of a surface expression.
                active_key = field.upper().lstrip("*")
                i += 1
                key_opts[active_key] = option_fields[i]
                if field.startswith("*") and active_key == "FILL":
                    key_opts["FILL_STAR"] = "1"
            elif active_key is not None:
                # Keep collecting values for options like FILL with ranges/lists.
                key_opts[active_key] = (key_opts.get(active_key, "") + " " + field).strip()
            else:
                geom_fields.append(field)
            i += 1

        geom_expr = ' '.join(geom_fields)
        raw_geom_expr = geom_expr


        cell = cls(cell_id, mat_id, dens, geom_expr, key_opts, raw_geom_expr)

        return cell

    @staticmethod
    def _parse_impn(key_opts: dict) -> int:
        # Prefer explicit IMP:N, fallback to variants like IMP:N,P.
        cand = None
        if "IMP:N" in key_opts:
            cand = key_opts.get("IMP:N")
        else:
            for k, v in key_opts.items():
                if k.startswith("IMP:N"):
                    cand = v
                    break
        if cand is None:
            return 1
        tok = str(cand).strip().split()
        if not tok:
            return 1
        try:
            return int(float(tok[0]))
        except Exception:
            return 1

    @staticmethod
    def _parse_fill(raw: str, is_star: bool = False) -> MFillSpec | None:
        raw = raw.strip()
        if not raw:
            return None

        # Simple form: FILL=u or FILL=u(transform).  Parentheses may contain
        # either a TR number or an inline displacement/rotation specification.
        msimple = re.fullmatch(r"\s*([+-]?\d+)\s*(?:\((.*?)\))?\s*", raw, re.DOTALL)
        if msimple is not None:
            transform = msimple.group(2)
            if transform is not None:
                transform = transform.strip() or None
            return MFillSpec(
                raw=raw,
                universe=int(msimple.group(1)),
                transform=transform,
                is_star=is_star,
            )

        # Indexed lattice form begins with two or three i:j ranges.  Entries
        # may themselves carry transforms, e.g. 2(3), 4 (2), 4(5 0 0), and
        # MCNP's nR repeat notation repeats both the universe and transform.
        pos = 0
        ranges = []
        while len(ranges) < 3:
            mr = re.match(r"\s*([+-]?\d+)\s*:\s*([+-]?\d+)", raw[pos:])
            if mr is None:
                break
            ranges.append((int(mr.group(1)), int(mr.group(2))))
            pos += mr.end()
        if len(ranges) not in (2, 3):
            return MFillSpec(raw=raw, universe=None, is_star=is_star)

        entries: list[int] = []
        transforms: list[str | None] = []
        n = len(raw)
        while pos < n:
            while pos < n and (raw[pos].isspace() or raw[pos] == ","):
                pos += 1
            if pos >= n:
                break

            mrep = re.match(r"(\d+)[Rr](?=\s|,|$)", raw[pos:])
            if mrep is not None:
                if not entries:
                    return MFillSpec(raw=raw, universe=None, is_star=is_star)
                for _ in range(int(mrep.group(1))):
                    entries.append(entries[-1])
                    transforms.append(transforms[-1])
                pos += mrep.end()
                continue

            ment = re.match(r"([+-]?\d+)", raw[pos:])
            if ment is None:
                return MFillSpec(raw=raw, universe=None, is_star=is_star)
            entries.append(int(ment.group(1)))
            transforms.append(None)
            pos += ment.end()

            save = pos
            while pos < n and raw[pos].isspace():
                pos += 1
            if pos < n and raw[pos] == "(":
                close = raw.find(")", pos + 1)
                if close < 0:
                    return MFillSpec(raw=raw, universe=None, is_star=is_star)
                transform = raw[pos + 1:close].strip()
                transforms[-1] = transform or None
                pos = close + 1
            else:
                pos = save

        return MFillSpec(
            raw=raw,
            universe=None,
            ranges=tuple(ranges),
            entries=tuple(entries),
            entry_transforms=tuple(transforms),
            is_star=is_star,
        )



    def _process_geom_expr(self):
        self._geom_AST = parse_geom_expr(self._geom_expr)
        self._surf_ids = list(collect_surface_ids(self._geom_AST))

        





    def update_geometry_AST(self):
        if self._geom_AST is None:
            self._geom_AST = parse_geom_expr(self._geom_expr)



    '''
    对几何体的面表达式进行分组，分组后每个组内为多个几何面的同一类型布尔操作，相邻分组间再依次通过布尔操作构成最终几何体。
    本函数返回值group_surfs为每个分组内各面的有向序号，group_types为各个分组内部的布尔操作，group_opers为组间的布尔操作。
    如对表达式"+1 -2 +3 -6 : -2 +4 -3", group_surfs=[(+1 -2 +3 -6), (-2 +4 -3)], group_types=[MBooleanOper.Intersection, MBooleanOper.Intersection], group_opers=[MBooleanOper.Union]
    '''
    def _group_geom_expr(self):
        group_surfs, group_types, group_opers = [], [], []

        self._geom_expr = re.sub(r"\s+", " ", self._geom_expr)
        # 最常见情形：全部为面定义的半空间的交集，且不包含括号，如"1 -2 3 -4  5 -6"
        if ':' not in self._geom_expr and '(' not in self._geom_expr:
            group_surfs.append(list(map(int, self._geom_expr.split())))
            group_types.append(MBooleanOper.INTERSECTION)

            return [group_surfs, group_types, group_opers]
        

        # 提取所有括号内的内容
        sections = re.findall(r'\((.*?)\)', self._geom_expr)
        tmp_expr = self._geom_expr
        for isec, sec in enumerate(sections):
            tmp_expr = tmp_expr.replace(f'({sec})', f'%_{isec}')


        if ':' not in tmp_expr:
            fields = tmp_expr.split()
            surfaces = []
            for field in fields:
                if field.startswith('%_'):
                    if surfaces:
                        group_surfs.append(surfaces)
                        group_types.append(MBooleanOper.INTERSECTION)
                    isec = int(field[2:])
                    section = sections[isec]
                    if ":" in section:
                        group_types.append(MBooleanOper.UNION)
                        surfaces = list(map(int, section.split(":")))
                    else:
                        group_types.append(MBooleanOper.INTERSECTION)
                        surfaces = list(map(int, section.split()))
                    group_surfs.append(surfaces)
                    surfaces = []
                else:
                    surfaces.append(int(field))
            
            if surfaces:
                group_surfs.append(surfaces)
                group_types.append(MBooleanOper.INTERSECTION)

            ngroup = len(group_types)
            group_opers = [MBooleanOper.INTERSECTION for ifield in range(ngroup-1)]
        else:
            fields = tmp_expr.split(':')
            for field in fields:
                surfaces = []
                if field.startswith('%_'):
                    isec = int(field[2:])
                    section = sections[isec]
                     
                    if ":" in section:
                        group_types.append(MBooleanOper.UNION)
                        surfaces = list(map(int, section.split(":")))
                    else:
                        group_types.append(MBooleanOper.INTERSECTION)
                        surfaces = list(map(int, section.split()))
                else:
                    surfaces = list(map(int, field.split()))
                    group_types.append(MBooleanOper.INTERSECTION)

                group_surfs.append(surfaces)
               
            

            ngroup = len(group_types)
            group_opers = [MBooleanOper.UNION for ifield in range(ngroup-1)]


        #对"+1:-2:+3:-4:+5:-6"这种类型的表达式，视为一个整体并转换为交集的补
        count_U = group_opers.count(MBooleanOper.UNION)    
        if (count_U > 0 and count_U == len(group_opers)):
            if re.fullmatch(PAT_UNION, self._geom_expr, re.VERBOSE) is not None:
                complement  =  [-1*isurf[0] for isurf in group_surfs]
                group_surfs = [complement]
                group_types = [MBooleanOper.COMPLEMENT]
                group_opers = []
        
        
        #将其他分组中的并集转换为补集，如"(1 2 3 4) (-5:6:-7:8)" 转换为 "(1 2 3 4) C(5 6 7 8)"
        for igrp, group_type in enumerate(group_types):
            if group_type == MBooleanOper.UNION:
                complement =  [-1*isurf for isurf in group_surfs[igrp]]
                group_surfs[igrp] = complement
                group_types[igrp] = MBooleanOper.COMPLEMENT


        if group_types[0] == MBooleanOper.COMPLEMENT and len(group_types) > 1:
            surfs = group_surfs[0]
            group_surfs[0] = group_surfs[1]
            group_surfs[1] = surfs        
            
            group_types[0] = group_types[1]
            group_types[1] = MBooleanOper.INTERSECTION
            group_opers[0] = MBooleanOper.SUBTRACTION


            
        for igrp, group_type in enumerate(group_types):
            if group_type == MBooleanOper.COMPLEMENT and igrp > 0:
                group_types[igrp] = MBooleanOper.INTERSECTION
                group_opers[igrp-1] = MBooleanOper.SUBTRACTION
            


        return [group_surfs, group_types, group_opers]







    @property
    def cell_id(self):
        return self._cell_id



    @property
    def mat_id(self):
        return self._mat_id



    @property
    def density(self):
        return self._density


    @property
    def impn(self):
        return self._impn



    @property
    def geom_expr(self):
        return self._geom_expr



    @property
    def surf_ids(self):
        return self._surf_ids


    @property
    def surfaces(self):
        return self._surfaces


    @property
    def geom_AST(self):
        return self._geom_AST

    @property
    def raw_geom_expr(self):
        return self._raw_geom_expr

    @property
    def key_opts(self):
        return self._key_opts

    @property
    def universe(self):
        return self._universe

    @property
    def lat(self):
        return self._lat

    @property
    def fill(self):
        return self._fill

    @property
    def fill_universe(self):
        if self._fill is None:
            return None
        return self._fill.universe


    @impn.setter
    def impn(self, value):
        self._impn = value



    @surfaces.setter
    def surfaces(self, surf_list: List[MSurface, ...]):
        self._surfaces = surf_list
