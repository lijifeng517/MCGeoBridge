
from .MUtil import str2float
from enum import Enum

class MSurfType(Enum):
    P = "P"
    SO = "SPHERE"
    SPH = "SPH"
    RPP = "RPP"
    RCC = "RCC"
    RHP = "RHP"
    PX = "PX"
    PY = "PY"
    PZ = "PZ"
    CX = "CX"
    CY = "CY"
    CZ = "CZ"
    C_X = "C/X"
    C_Y = "C/Y"
    C_Z = "C/Z"
    C_G = "C/G"
    TX = "TX"
    TY = "TY"
    TZ = "TZ"
    BOX = "BOX"
    SQ = "SQ"
    GQ = "GQ"
    KX = "KX"
    KY = "KY"
    KZ = "KZ"
    K_X = "K/X"
    K_Y = "K/Y"
    K_Z = "K/Z"
    X = "X"
    Y = "Y"
    Z = "Z"
    ELL_G = "ELL/G"
    ECYL_G = "ECYL/G"
    CONE_G = "CONE/G"
    TRC = "TRC"

        


class MSurface:
    def __init__(self, sid: int, stype: MSurfType, params: list[float, ...],
                 transform_id: int | None = None, boundary: str = ""):
        self._sid    = sid
        self._stype  = stype
        self._params = params
        self._transform_id = transform_id
        self._boundary = boundary


    @classmethod
    def create_from_str(cls, data_str: str):
        fields = data_str.split()
        if len(fields) < 2:
            raise ValueError(f"Invalid surface data line: '{data_str}'")

        sid_token = fields[0]
        boundary = sid_token[0] if sid_token[:1] in ("*", "+") else ""
        if boundary:
            sid_token = sid_token[1:]
        sid = int(sid_token)

        type_index = 1
        transform_id = None
        if len(fields) >= 3 and fields[1].lstrip("+-").isdigit():
            transform_id = int(fields[1])
            type_index = 2

        raw_stype = fields[type_index].upper().replace("/", "_")
        raw_params = list(map(str2float, fields[type_index + 1:]))

        # MCNP sphere variants share one canonical representation internally.
        # This keeps the converter/evaluator paths small while accepting the
        # standard S, SX, SY, and SZ surface cards.
        if raw_stype in ("X", "Y", "Z") and len(raw_params) >= 6:
            u1, r1, u2, r2, u3, r3 = raw_params[0:6]
            mid = 0.5 * (u1 + u3)
            scale = max(1.0, abs(u1), abs(u2), abs(u3), abs(r2))
            if abs(r1) <= 1e-10 * scale and abs(r3) <= 1e-10 * scale and abs(u2 - mid) <= 1e-8 * scale and r2 > 0:
                axial = 0.5 * abs(u3 - u1)
                if raw_stype == "X":
                    center = (mid, 0.0, 0.0)
                    radii = (axial, r2, r2)
                elif raw_stype == "Y":
                    center = (0.0, mid, 0.0)
                    radii = (r2, axial, r2)
                else:
                    center = (0.0, 0.0, mid)
                    radii = (r2, r2, axial)
                stype = "ELL_G"
                params = [
                    *center,
                    1.0, 0.0, 0.0,
                    0.0, 1.0, 0.0,
                    0.0, 0.0, 1.0,
                    *radii,
                ]
            else:
                stype = raw_stype
                params = raw_params
        elif raw_stype == "S":
            stype = "SPH"
            params = raw_params
        elif raw_stype == "SX" and len(raw_params) >= 2:
            stype = "SPH"
            params = [raw_params[0], 0.0, 0.0, raw_params[1]]
        elif raw_stype == "SY" and len(raw_params) >= 2:
            stype = "SPH"
            params = [0.0, raw_params[0], 0.0, raw_params[1]]
        elif raw_stype == "SZ" and len(raw_params) >= 2:
            stype = "SPH"
            params = [0.0, 0.0, raw_params[0], raw_params[1]]
        else:
            stype = raw_stype
            params = raw_params
        if stype not in MSurfType.__members__:
            raise ValueError(f"Unknown surface type {stype} in data line: '{data_str}'")

        surf = cls(sid, MSurfType[stype], params, transform_id, boundary)

        return surf



    @property
    def sid(self):
        return self._sid



    @property
    def stype(self):
        return self._stype



    @property
    def params(self):
        return self._params

    @property
    def transform_id(self):
        return self._transform_id

    @property
    def boundary(self):
        return self._boundary
