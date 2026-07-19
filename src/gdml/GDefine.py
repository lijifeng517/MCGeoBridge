

import xml.etree.ElementTree as ET

class GDefine:
    def __init__(self, name, the_type='define'):
        self._name = name
        self._type = the_type
        

    def write_gdml(self, xml_defines):
        raise NotImplementedError("Need to be implemented in derived class")



    @property
    def name(self):
        return self._name

    
    @property
    def type(self):
        return self._type




class GConstant(GDefine):
    def __init__(self, name, value):
        super().__init__(name, 'constant')
        self._value = value



    def write_gdml(self, xml_defines):
        xml_const = ET.SubElement(xml_defines, f"{self._type}")
        xml_const.set("name", f"{self._name}")
        xml_const.set("value", f"{self._value}")




    @property
    def value(self):
        return self._value

    




class GVector(GDefine):
    def __init__(self, name, the_type, unit, x=0.0, y=0.0, z=0.0):
        if the_type not in ("position", "rotation"):
            raise ValueError(f"Invalid value {the_type} for instance of GVector")

        super().__init__(name, the_type)

        self._x = x
        self._y = y
        self._z = z
        self._unit = unit


    def write_gdml(self, xml_defines):
        xml_vec = ET.SubElement(xml_defines, f"{self._type}")
        xml_vec.set("name", f"{self._name}")
        xml_vec.set("unit", f"{self._unit}")
        xml_vec.set("x", f"{self._x}")
        xml_vec.set("y", f"{self._y}")
        xml_vec.set("z", f"{self._z}")


    @property
    def x(self):
        return self._x


    @property
    def y(self):
        return self._y


    @property
    def z(self):
        return self._z

    @property
    def unit(self):
        return self._unit
