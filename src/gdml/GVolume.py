

import xml.etree.ElementTree as ET

class GVolume():
    def __init__(self, name, mat_ref, solid_ref):
        self._name = name
        self._mat_ref = mat_ref
        self._solid_ref = solid_ref
        self._physvols = []
        


    def add_physvol(self, physvol):
        self._physvols.append(physvol)

        

    def write_gdml(self, xml_structure):
        xml_volume = ET.SubElement(xml_structure, "volume")
        xml_volume.set("name", self._name)

        xml_mat_ref = ET.SubElement(xml_volume, "materialref")        
        xml_mat_ref.set("ref", self._mat_ref)
        
        xml_solid_ref = ET.SubElement(xml_volume, "solidref")
        xml_solid_ref.set("ref", self._solid_ref)

        for physvol in self._physvols:
            physvol.write_gdml(xml_volume)



    @property
    def name(self):
        return self._name

    

    @property
    def mat_ref(self):
        return self._mat_ref



    @property
    def solid_ref(self):
        return self._solid_ref


    @property
    def physvols(self):
        return self._physvols





class GPhysicalVolume():
    def __init__(self, name, vol_ref, pos_ref, rot_ref):
        self._name = name
        self._vol_ref = vol_ref
        self._pos_ref = pos_ref
        self._rot_ref = rot_ref
        


    def write_gdml(self, xml_volume):
        xml_physvol = ET.SubElement(xml_volume, "physvol")

        xml_vol_ref = ET.SubElement(xml_physvol, "volumeref")        
        xml_vol_ref.set("ref", self._vol_ref)
        
        xml_pos_ref = ET.SubElement(xml_physvol, "positionref")
        xml_pos_ref.set("ref", self._pos_ref)

        xml_rot_ref = ET.SubElement(xml_physvol, "rotationref")
        xml_rot_ref.set("ref", self._rot_ref)


    @property
    def name(self):
        return self._name

    

    @property
    def vol_ref(self):
        return self._vol_ref



    @property
    def pos_ref(self):
        return self._pos_ref


    @property
    def rot_ref(self):
        return self._rot_ref




