
import xml.etree.ElementTree as ET

class GMaterial:
    def __init__(self, name, type='GMaterial'):
        self._name = name
        self._type = type


    def write_gdml(self, xml_materials):
        raise NotImplementedError("Need to be implemented in derived class")

    
    @property
    def name(self):
        return self._name



    @property
    def type(self):
        return self._type





class GIsotope(GMaterial):
    """A named isotope for isotope-resolved GDML material definitions."""
    def __init__(self, name: str, ZZZ: int, nucleon_number: int, atomic_val: float):
        super().__init__(name, 'GIsotope')
        self._ZZZ = ZZZ
        self._nucleon_number = nucleon_number
        self._atomic_val = atomic_val

    def write_gdml(self, xml_materials):
        xml_isotope = ET.SubElement(xml_materials, "isotope")
        xml_isotope.set("name", f"{self._name}")
        xml_isotope.set("Z", f"{self._ZZZ}")
        # GDML calls this attribute N, but the schema uses it for the
        # nuclide mass (nucleon) number A, not the neutron count A-Z.
        xml_isotope.set("N", f"{self._nucleon_number}")
        xml_atom = ET.SubElement(xml_isotope, "atom")
        xml_atom.set("value", f"{self._atomic_val}")


class GElement(GMaterial):
    def __init__(self, name: str, ZZZ: int, formula: str, atomic_val: float,
                 isotope_ref: str = None):
        super().__init__(name, 'GElement')

        self._formula = formula
        self._ZZZ =   ZZZ
        self._atomic_val = atomic_val
        self._isotope_ref = isotope_ref
        


    def write_gdml(self, xml_materials):
        xml_elem = ET.SubElement(xml_materials, "element")
        xml_elem.set("name", f"{self._name}")
        xml_elem.set("Z", f"{self._ZZZ}")
        
        xml_elem.set("formula", f"{self._formula}")
        if self._isotope_ref is None:
            xlm_atom = ET.SubElement(xml_elem, "atom")
            xlm_atom.set("value", f"{self._atomic_val}")
        else:
            xml_fraction = ET.SubElement(xml_elem, "fraction")
            xml_fraction.set("ref", f"{self._isotope_ref}")
            xml_fraction.set("n", "1.0")


    
    @property
    def ZZZ(self):
        return self._ZZZ


    @property
    def formula(self):
        return self._formula


    @property
    def atomic_val(self):
        return self._atomic_val

        




class GMixture(GMaterial):
    def __init__(self, name, DDD=1.0):
        super().__init__(name, 'GMixture')
        self._DDD  = DDD
        self._fractions = {}
        

    def add_fraction(self, frac_ref, frac_n):
        self._fractions[frac_ref] = frac_n



    def write_gdml(self, xml_materials):
        xml_mat = ET.SubElement(xml_materials, "material")
        xml_mat.set("name", f"{self._name}")
        
        xml_dd  = ET.SubElement(xml_mat, "D")
        xml_dd.set("value", f"{self._DDD}")
        xml_dd.set("unit", "g/cm3")

        refs = self._fractions.keys()
        for ref in refs:
            xml_frac = ET.SubElement(xml_mat, "fraction")
            xml_frac.set("ref", f"{ref}")
            xml_frac.set("n",   f"{self._fractions[ref]}")


    
    @property
    def DDD(self):
        return self._DDD


    @property
    def fractions(self):
        return self._fractions

