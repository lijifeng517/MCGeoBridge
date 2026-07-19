
import xml.etree.ElementTree as ET

from .GDefine import GDefine
from .GMaterial import GMaterial
from .GSolid import GSolid
from .GVolume import GVolume


class GModel():
    _instance = None
    def __new__(cls):
        if cls._instance == None:
            cls._instance = super().__new__(cls)
            cls._instance._name = ''
            cls._instance._defines = []
            cls._instance._materials = []
            cls._instance._solids = []
            cls._instance._volumes = []
        
        return cls._instance




    def set_name(self, name):
        self._name = name



    def add_define(self, gDefine):
        if not isinstance(gDefine, GDefine):
            raise TypeError("Error! A GDefine type expected in function GModel:add_define.")
        self._defines.append(gDefine)




    def add_material(self, gMaterial):
        if not isinstance(gMaterial, GMaterial):
            raise TypeError("Error! A GMaterial type expected in function GModel:add_material.")
        self._materials.append(gMaterial)




    def add_solid(self, gSolid):
        if not isinstance(gSolid, GSolid):
            raise TypeError("Error! A GSolid type expected in function GModel:add_solid.")
        self._solids.append(gSolid)




    def add_volume(self, gVolume):
        if not isinstance(gVolume, GVolume):
            raise TypeError("Error! A GVolume type expected in function GModel:add_volume.")
        self._volumes.append(gVolume)




    def write_gdml(self, gdml_fname):
        el_gdml = ET.Element("gdml")
        el_gdml.set("xmlns:gdml", "http://cern.ch/2001/Schemas/GDML")
        el_gdml.set("xmlns:xsi",  "http://www.w3.org/2001/XMLSchema-instance")
        el_gdml.set("xsi:noNamespaceSchemaLocation", "gdml.xsd")
        
        
        el_defines = ET.SubElement(el_gdml, "define")
        for define in self._defines:
            define.write_gdml(el_defines)
        

        el_materials = ET.SubElement(el_gdml, "materials")
        for material in self._materials:
            material.write_gdml(el_materials)


        el_solids = ET.SubElement(el_gdml, "solids")
        for solid in self._solids:
            solid.write_gdml(el_solids)

       
        el_structure = ET.SubElement(el_gdml, "structure")
        # Geant4's GDML reader resolves volumeref entries while parsing and
        # does not accept a reference to a volume defined later in the file.
        # Emit a dependency-first topological order (World therefore appears
        # after all of its daughters).
        volume_by_name = {volume.name: volume for volume in self._volumes}
        ordered_volumes = []
        visiting = set()
        visited = set()

        def visit(volume):
            if volume.name in visited:
                return
            if volume.name in visiting:
                raise ValueError(f"Cyclic GDML volume dependency at {volume.name}")
            visiting.add(volume.name)
            for physvol in volume.physvols:
                dependency = volume_by_name.get(physvol.vol_ref)
                if dependency is not None:
                    visit(dependency)
            visiting.remove(volume.name)
            visited.add(volume.name)
            ordered_volumes.append(volume)

        for volume in self._volumes:
            visit(volume)
        for volume in ordered_volumes:
            volume.write_gdml(el_structure)
        

        
        el_setup = ET.SubElement(el_gdml, "setup")
        el_setup.set("name", "Default")
        el_setup.set("version", "1.0")

        el_world = ET.SubElement(el_setup, "world")
        el_world.set("ref", "World")


        tree = ET.ElementTree(el_gdml)
        ET.indent(tree, space="  ", level=0)
        with open(gdml_fname, 'wb') as gdml_file:
            tree.write(gdml_file, encoding='utf-8', xml_declaration=True)






    @property
    def name(self):
        return self._name

    

    @property
    def defines(self):
        return self._defines




    @property
    def materials(self):
        return self._materials



    @property
    def solids(self):
        return self._solids


    @property
    def volumes(self):
        return self._volumes

