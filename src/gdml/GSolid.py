

import xml.etree.ElementTree as ET


def _fmt(value):
    """Preserve MCNP geometry precision without verbose binary tails."""
    return f"{float(value):.12g}"

class GSolid():
    def __init__(self, name, type='solid', lunit='cm', aunit='deg'):
        self._name = name
        self._type = type
        self._lunit = lunit
        self._aunit = aunit        


    def write_gdml(self, xml_solids):
        raise NotImplementedError("Need to be implemented in derived class")



    @property
    def name(self):
        return self._name

    
    @property
    def type(self):
        return self._type


    @property
    def lunit(self):
        return self._lunit


    @property
    def aunit(self):
        return self._aunit





class GBox(GSolid):
    def __init__(self, name, xlen, ylen, zlen, lunit='cm', aunit='deg'):
        super().__init__(name, "box", lunit, aunit)

        self._xlen = xlen
        self._ylen = ylen
        self._zlen = zlen



    def write_gdml(self, xml_solids):
        xml_box = ET.SubElement(xml_solids, f"{self._type}")
        xml_box.set("name", f"{self._name}")
        xml_box.set("x", _fmt(self._xlen))
        xml_box.set("y", _fmt(self._ylen))
        xml_box.set("z", _fmt(self._zlen))
        xml_box.set("lunit", f"{self._lunit}")
        xml_box.set("aunit", f"{self._aunit}")






class GSphere(GSolid):
    def __init__(self, name, rmax, rmin=0.0, startphi=0.0, deltaphi=360, starttheta=0.0, deltatheta=180, lunit='cm', aunit='deg'):
        super().__init__(name , 'sphere', lunit, aunit)

        self._rmax = rmax
        self._rmin = rmin
        self._startphi = startphi
        self._deltaphi = deltaphi
        self._starttheta = starttheta
        self._deltatheta = deltatheta



    def write_gdml(self, xml_solids):
        xml_sphere = ET.SubElement(xml_solids, f"{self._type}")
        xml_sphere.set("name", f"{self._name}")
        xml_sphere.set("rmin", _fmt(self._rmin))
        xml_sphere.set("rmax", _fmt(self._rmax))
        xml_sphere.set("startphi", _fmt(self._startphi))
        xml_sphere.set("deltaphi", _fmt(self._deltaphi))
        xml_sphere.set("starttheta", _fmt(self._starttheta))
        xml_sphere.set("deltatheta", _fmt(self._deltatheta))
        xml_sphere.set("lunit", f"{self._lunit}")
        xml_sphere.set("aunit", f"{self._aunit}")






class GTube(GSolid):
    def __init__(self, name, rmax, z, rmin=0.0, startphi=0.0, deltaphi=360, lunit='cm', aunit='deg'):
        super().__init__(name , 'tube', lunit, aunit)

        self._rmax = rmax
        self._rmin = rmin
        self._startphi = startphi
        self._deltaphi = deltaphi
        self._z = z



    def write_gdml(self, xml_solids):
        xml_tube = ET.SubElement(xml_solids, f"{self._type}")
        xml_tube.set("name", f"{self._name}")
        xml_tube.set("rmin", _fmt(self._rmin))
        xml_tube.set("rmax", _fmt(self._rmax))
        xml_tube.set("startphi", _fmt(self._startphi))
        xml_tube.set("deltaphi", _fmt(self._deltaphi))
        xml_tube.set("z", _fmt(self._z))
        xml_tube.set("lunit", f"{self._lunit}")
        xml_tube.set("aunit", f"{self._aunit}")


class GTorus(GSolid):
    def __init__(self, name, rtor, rmax, rmin=0.0, startphi=0.0,
                 deltaphi=360.0, lunit='cm', aunit='deg'):
        super().__init__(name, 'torus', lunit, aunit)
        self._rtor = rtor
        self._rmax = rmax
        self._rmin = rmin
        self._startphi = startphi
        self._deltaphi = deltaphi

    def write_gdml(self, xml_solids):
        xml_torus = ET.SubElement(xml_solids, self._type)
        xml_torus.set("name", f"{self._name}")
        xml_torus.set("rtor", f"{self._rtor:.8g}")
        xml_torus.set("rmin", f"{self._rmin:.8g}")
        xml_torus.set("rmax", f"{self._rmax:.8g}")
        xml_torus.set("startphi", f"{self._startphi:.8g}")
        xml_torus.set("deltaphi", f"{self._deltaphi:.8g}")
        xml_torus.set("lunit", f"{self._lunit}")
        xml_torus.set("aunit", f"{self._aunit}")


class GGenericPolycone(GSolid):
    def __init__(self, name, rzpoints, startphi=0.0, deltaphi=360.0,
                 lunit='cm', aunit='deg'):
        super().__init__(name, 'genericPolycone', lunit, aunit)
        self._rzpoints = list(rzpoints)
        self._startphi = startphi
        self._deltaphi = deltaphi

    def write_gdml(self, xml_solids):
        xml_poly = ET.SubElement(xml_solids, self._type)
        xml_poly.set("name", f"{self._name}")
        xml_poly.set("startphi", f"{self._startphi:.8g}")
        xml_poly.set("deltaphi", f"{self._deltaphi:.8g}")
        xml_poly.set("lunit", f"{self._lunit}")
        xml_poly.set("aunit", f"{self._aunit}")
        for radius, z in self._rzpoints:
            point = ET.SubElement(xml_poly, "rzpoint")
            point.set("r", f"{radius:.10g}")
            point.set("z", f"{z:.10g}")


class GEllipticalTube(GSolid):
    def __init__(self, name, dx, dy, dz, lunit='cm', aunit='deg'):
        super().__init__(name, 'eltube', lunit, aunit)
        self._dx = dx
        self._dy = dy
        self._dz = dz

    def write_gdml(self, xml_solids):
        xml_tube = ET.SubElement(xml_solids, self._type)
        xml_tube.set("name", f"{self._name}")
        xml_tube.set("dx", f"{self._dx:.8g}")
        xml_tube.set("dy", f"{self._dy:.8g}")
        xml_tube.set("dz", f"{self._dz:.8g}")
        xml_tube.set("lunit", f"{self._lunit}")


class GEllipsoid(GSolid):
    def __init__(self, name, ax, by, cz, zcut1=None, zcut2=None,
                 lunit='cm', aunit='deg'):
        super().__init__(name, 'ellipsoid', lunit, aunit)
        self._ax = ax
        self._by = by
        self._cz = cz
        self._zcut1 = -cz if zcut1 is None else zcut1
        self._zcut2 = cz if zcut2 is None else zcut2

    def write_gdml(self, xml_solids):
        xml_ell = ET.SubElement(xml_solids, self._type)
        xml_ell.set("name", f"{self._name}")
        xml_ell.set("ax", f"{self._ax:.8g}")
        xml_ell.set("by", f"{self._by:.8g}")
        xml_ell.set("cz", f"{self._cz:.8g}")
        xml_ell.set("zcut1", f"{self._zcut1:.8g}")
        xml_ell.set("zcut2", f"{self._zcut2:.8g}")
        xml_ell.set("lunit", f"{self._lunit}")


class GCons(GSolid):
    def __init__(self, name, rmax1, rmax2, z, rmin1=0.0, rmin2=0.0,
                 startphi=0.0, deltaphi=360.0, lunit='cm', aunit='deg'):
        super().__init__(name, 'cone', lunit, aunit)
        self._rmax1 = rmax1
        self._rmax2 = rmax2
        self._rmin1 = rmin1
        self._rmin2 = rmin2
        self._z = z
        self._startphi = startphi
        self._deltaphi = deltaphi

    def write_gdml(self, xml_solids):
        xml_cone = ET.SubElement(xml_solids, self._type)
        xml_cone.set("name", f"{self._name}")
        xml_cone.set("rmin1", f"{self._rmin1:.8g}")
        xml_cone.set("rmax1", f"{self._rmax1:.8g}")
        xml_cone.set("rmin2", f"{self._rmin2:.8g}")
        xml_cone.set("rmax2", f"{self._rmax2:.8g}")
        xml_cone.set("z", f"{self._z:.8g}")
        xml_cone.set("startphi", f"{self._startphi:.8g}")
        xml_cone.set("deltaphi", f"{self._deltaphi:.8g}")
        xml_cone.set("lunit", f"{self._lunit}")
        xml_cone.set("aunit", f"{self._aunit}")


class GPolyhedra(GSolid):
    def __init__(self, name, numsides, zplanes, startphi=0.0, deltaphi=360.0, lunit='cm', aunit='deg'):
        super().__init__(name, "polyhedra", lunit, aunit)
        self._numsides = int(numsides)
        self._zplanes = list(zplanes)  # [(z, rmin, rmax), ...]
        self._startphi = float(startphi)
        self._deltaphi = float(deltaphi)

    def write_gdml(self, xml_solids):
        xml_poly = ET.SubElement(xml_solids, f"{self._type}")
        xml_poly.set("name", f"{self._name}")
        xml_poly.set("numsides", f"{self._numsides}")
        xml_poly.set("startphi", f"{self._startphi:.6f}")
        xml_poly.set("deltaphi", f"{self._deltaphi:.6f}")
        xml_poly.set("lunit", f"{self._lunit}")
        xml_poly.set("aunit", f"{self._aunit}")

        for z, rmin, rmax in self._zplanes:
            xml_zp = ET.SubElement(xml_poly, "zplane")
            xml_zp.set("z", f"{float(z):.6f}")
            xml_zp.set("rmin", f"{float(rmin):.6f}")
            xml_zp.set("rmax", f"{float(rmax):.6f}")




class GBooleanSolid(GSolid):
    def __init__(self, name, bType, first, second, pos_ref, rot_ref, lunit='cm', aunit='deg'):
        super().__init__(name, bType, lunit, aunit)

        self._first  = first
        self._second = second

        self._posref = pos_ref
        self._rotref = rot_ref



    def write_gdml(self, xml_solids):
        xml_bSolid = ET.SubElement(xml_solids, f"{self._type}")
        xml_bSolid.set("name", f"{self._name}")

        xml_solid1 = ET.SubElement(xml_bSolid, "first")
        xml_solid1.set("ref", f"{self._first}")
   
        xml_solid2 = ET.SubElement(xml_bSolid, "second")
        xml_solid2.set("ref", f"{self._second}")

        xml_posref = ET.SubElement(xml_bSolid, "position")
        xml_posref.set("name", f"Pos_{self._name}")
        xml_posref.set("x", f"{self._posref.x}")
        xml_posref.set("y", f"{self._posref.y}")
        xml_posref.set("z", f"{self._posref.z}")
        if hasattr(self._posref, "unit"):
            xml_posref.set("unit", f"{self._posref.unit}")

        xml_rotref = ET.SubElement(xml_bSolid, "rotation")
        xml_rotref.set("name", f"Rot_{self._name}")
        xml_rotref.set("x", f"{self._rotref.x}")
        xml_rotref.set("y", f"{self._rotref.y}")
        xml_rotref.set("z", f"{self._rotref.z}")
        if hasattr(self._rotref, "unit"):
            xml_rotref.set("unit", f"{self._rotref.unit}")
