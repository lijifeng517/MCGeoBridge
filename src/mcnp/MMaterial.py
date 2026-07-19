
import os
import re
from .MUtil import str2float


MCOMP_PAT = r'^(\d{1,3})(\d{3})(?:\.(\d{2}[a-zA-Z]?))?$'


class MElement:
    def __init__(self, name: str, ZZZ: int, mass: float):
        self._name = name
        self._ZZZ  = ZZZ
        self._mass = mass


    @property
    def name(self):
        return self._name


    @property
    def ZZZ(self):
        return self._ZZZ


    @property
    def mass(self):
        return self._mass



class MMaterial:
    def __init__(self, mat_id: int, name: str = None):
        self._mat_id    = mat_id
        self._name      = f"M{mat_id:>08d}" if name is None else name
        self._fractions = {}



    def add_fraction(self, mElem: MElement, frac_val: float):
        self._fractions[mElem] = frac_val        




    @classmethod
    def create_from_str(cls, data_str: str):
        fields = data_str.split()
        mat_id = int(fields[0][1:])
    
        mat = cls(mat_id)

        script_path = os.path.abspath(__file__)
        script_dir  = os.path.dirname(script_path)
        MLIB_FPATH  = os.path.join(script_dir, 'csindex')

        mass_by_name = {}
        with open(MLIB_FPATH, 'r') as mlib_fp:
            for line in mlib_fp:
                mlib_fields = line.split()
                if len(mlib_fields) >= 2:
                    raw_name = mlib_fields[0].split('.')[0].strip()
                    try:
                        raw_name = str(int(raw_name))
                    except ValueError:
                        pass
                    mass_by_name[raw_name] = str2float(mlib_fields[1])

        idx = 1
        while idx + 1 < len(fields):
            zaid = fields[idx]
            # Material options such as PLIB=84P and NLIB=... are not isotope
            # fraction pairs and terminate the composition list.
            if '=' in zaid or re.fullmatch(MCOMP_PAT, zaid) is None:
                idx += 1
                continue
            try:
                frac_val = str2float(fields[idx + 1])
            except Exception:
                idx += 1
                continue
            raw_elem_name = zaid.split('.')[0].strip()
            elem_number = int(raw_elem_name)
            # A fixed-width identifier is a valid XML ID and makes 1001 and
            # zero-padded 001001 spellings refer to the same isotope.
            elem_name = f"{elem_number:06d}"
            elem_ZZZ = int(elem_name[:-3])
            mass_number = int(elem_name[-3:])
            # A ZAID with a nonzero final field identifies a nuclide.  Use that
            # mass number rather than an xsdir atomic-weight entry: the latter
            # is library metadata and can be stale or inconsistent with the
            # requested ZAID.  This value is used for atom-to-mass conversion;
            # an approximate integer mass is preferable to silently selecting
            # a different isotope.  A=0 designators retain the library value.
            elem_mass = float(mass_number) if mass_number > 0 else mass_by_name.get(str(elem_number), 0.0)
             
            elem = MElement(elem_name, elem_ZZZ, elem_mass)
            mat.add_fraction(elem, frac_val)
            idx += 2

        return mat
            

            


    


    @property
    def mat_id(self):
        return self._mat_id


    @property
    def name(self):
        return self._name


    @property
    def fractions(self):
        return self._fractions
