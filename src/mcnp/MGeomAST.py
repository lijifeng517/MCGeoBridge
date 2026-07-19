from __future__ import annotations
import re
from enum import Enum

from .MSurface import MSurface, MSurfType
from .MUtil import str2float


class MBooleanOper(Enum):
    INTERSECTION = "Intersection"
    UNION        = "Union"
    COMPLEMENT   = "Complement"
    SUBTRACTION  = "Subtraction"



class MPrimitiveType(Enum):
    UNKNOWN   = "Unknown"
    BLOCK     = "Block"
    SPHERE    = "Sphere"
    CYLINDER  = "Cylinder"




class MCSGNode:
    _counter = 0
    _cell_id = 0

    @classmethod
    def set_id_prefix(cls, cell_id):
        cls._counter = 0
        cls._cell_id = cell_id


    def __init__(self):
        MCSGNode._counter += 1
        self._name = f"S_{MCSGNode._cell_id}_{MCSGNode._counter}"
        self._node_type = 'CSGNode'


    @property
    def name(self):
        return  self._name


    @name.setter
    def name(self, value):
        self._name = value



    @property
    def node_type(self):
        return self._node_type



    def str_expr(self):
        raise NotImplementedError("Need to be implemented in derived class")




class MPrimitiveNode(MCSGNode):
    def __init__(self, prim_type: MPrimitiveType, dimensions: Tuple[float, ...], position: Tuple[float, float, float], rotation: Tuple[float, float, float]):
        super().__init__()

        self._prim_type = prim_type
        self._dimensions = dimensions
        self._position  = position
        self._rotation  = rotation
        self._node_type  = 'primitive'


    def str_expr(self):
        params = ",".join(str(d) for d in self.dimensions)
        return f"{self.prim_type.value}(postions = {self._position}, dims = {params})"


    @property
    def prim_type(self):
        return self._prim_type


    @property
    def position(self):
        return self._position


    @property
    def rotation(self):
        return self._rotation


    @property
    def dimensions(self):
        return self._dimensions



class MBooleanNode(MCSGNode):
    def __init__(self, oper: MBooleanOper,  left: MCSGNode,  right: MCSGNode):
        super().__init__()

        self._oper  = oper
        self._left  = left
        self._right = right
        self._node_type = 'boolean'


    def str_expr(self):
        left_expr  = self._left.str_expr()
        right_expr = self._right.str_expr()

        return f"{self._oper.value}({left_expr}, {right_expr})" 
        

    @property
    def oper(self):
        return self._oper

    @property
    def left(self):
        return self._left


    @property
    def right(self):
        return self._right



class MGeomAST:
    def __init__(self):
        self._root  = None
        self._left  = None
        self._right = None


    def is_empty(self):
        return self._root is None



    def add_primitive(self, prim_type: MPrimitiveType,  dimensions: Tuple[float, ...], position: Tuple[float, float, float],  rotation: Tuple[float, float, float]):
        new_node = MPrimitiveNode(prim_type, dimensions, position, rotation)
        if self.is_empty():
            self._root = new_node
        else:
            self.apply_operation(MBooleanOper.UNION, new_node)



    def apply_operation(self, oper: MBooleanOper, other):
        if self.is_empty():
            raise ValueError("Cannot apply operation on empty tree")

        if isinstance(other, MGeomAST):
            if other.is_empty():
                raise ValueError("Cannot merge with empty tree")
            other_node = other._root
        else:
            other_node = other

        
        new_root = MBooleanNode(oper, self._root, other_node)
        self._root = new_root
        self._left  = self.root.left
        self._right = self.root.right



     
    def merge_tree(self, oper: MBooleanOper, other_tree: MGeomAST):
        self.apply_operation(oper, other_tree)






    def create_from_surfaces(self, cell_id, grouped_info, all_surfaces: List[MSurface, ...]):
        group_surf_ids, group_boolean_types, group_opers = grouped_info[:]
        group_prim_types = []
        MCSGNode.set_id_prefix(cell_id)
        for igrp, surf_ids in enumerate(group_surf_ids):
            my_surfaces = []
            for surf_id in surf_ids:
                for surface in all_surfaces:
                    if surface.sid == abs(surf_id):
                        my_surfaces.append(surface)
            surf_pairs = sorted(list(zip(surf_ids, my_surfaces)), key = lambda x: x[1].stype.value)
            
            prim_geom = self._build_geom_from_surfaces(surf_pairs)
            if self.is_empty():
                self._root = prim_geom
            else:
                self.apply_operation(group_opers[igrp-1], prim_geom)
            

        self._root.name = f"S_{cell_id}"




    def _build_geom_from_surfaces(self, surf_pairs):
        surf_ids, surfaces = zip(*surf_pairs)
        nsurf = len(surf_ids)
        surf_types = tuple(surf.stype for surf in surfaces)
        pos = [0.0, 0.0, 0.0]
        rot = [0.0, 0.0, 0.0]
        if nsurf == 1:
            if surf_types == (MSurfType.SO,):
                rad = surfaces[0].params[0]
                return MPrimitiveNode(MPrimitiveType.SPHERE, [rad], pos, rot)
        elif nsurf == 2:
            if surf_types == (MSurfType.SO, MSurfType.SO):
                rad0 = surfaces[0].params[0]
                rad1 = surfaces[1].params[0]
                rmin = min(rad0, rad1)
                rmax = max(rad0, rad1)
                return MPrimitiveNode(MPrimitiveType.SPHERE, [rmax, rmin], pos, rot)
        elif nsurf == 3:
            if (surf_types == (MSurfType.CX, MSurfType.PX, MSurfType.PX)) or   \
               (surf_types == (MSurfType.CY, MSurfType.PY, MSurfType.PY)) or   \
               (surf_types == (MSurfType.CZ, MSurfType.PZ, MSurfType.PZ)):
                rad, z0, z1 = (surfaces[isurf].params[0] for isurf in range(nsurf))
                zmin = min(z0, z1)
                zlen = abs(z1 - z0)
                pos = [0.0, 0.0, zmin]
                if surf_types[0] == MSurfType.CX:
                    rot = [0.0, 90.0, 0.0]
                elif surf_types[0] == MSurfType.CY:
                    rot = [-90, 0.0,  0.0]
                return MPrimitiveNode(MPrimitiveType.CYLINDER, [rad, zlen], pos, rot)
        elif nsurf == 4:
            if (surf_types == (MSurfType.CX, MSurfType.CX, MSurfType.PX, MSurfType.PX)) or    \
               (surf_types == (MSurfType.CY, MSurfType.CY, MSurfType.PY, MSurfType.PY)) or    \
               (surf_types == (MSurfType.CZ, MSurfType.CZ, MSurfType.PZ, MSurfType.PZ)):
                r0, r1, z0, z1 = (surfaces[isurf].params[0] for isurf in range(nsurf))
                rmin, rmax = sorted([r0, r1])
                zmin = min(z0, z1)
                zlen = abs(z1 - z0)
                pos = [0.0, 0.0, zmin]
                if surf_types[0] == MSurfType.CX:
                    rot = [0.0, 90.0, 0.0]
                elif surf_types[0] == MSurfType.CY:
                    rot = [-90, 0.0,  0.0]
                return MPrimitiveNode(MPrimitiveType.CYLINDER, [rmax, zlen, rmin], pos, rot)
        elif nsurf == 6:
            if (surf_types == (MSurfType.PX, MSurfType.PX, MSurfType.PY, MSurfType.PY, MSurfType.PZ, MSurfType.PZ)):
                x0, x1, y0, y1, z0, z1 = (surfaces[isurf].params[0] for isurf in range(nsurf))
                xmin, xmax = sorted([x0, x1])
                ymin, ymax = sorted([y0, y1])
                zmin, zmax = sorted([z0, z1])
                xlen, ylen, zlen = xmax - xmin, ymax - ymin, zmax - zmin
                pos = [xmin, ymin, zmin]
                return MPrimitiveNode(MPrimitiveType.BLOCK, [xlen, ylen, zlen], pos, rot)
        



        return MPrimitiveNode(MPrimitiveType.UNKNOWN, [], pos, rot)
               
            




    def str_expr(self):
        if self.is_empty():
            return "Empty geometry tree"

        return self._root.str_expr()




    def visualize(self, indent: int = 0):
        if self.is_empty():
            return "Empty geometry tree"

        return self._visualize_node(self._root, indent)




    def _visualize_node(self, node: MCSGNode,  indent: int):
        indent_str = " " * indent
        
        if isinstance(node, MPrimitiveNode):
            return f"{indent_str}Primitive({node.prim_type.value}. position={node.position}, dimensions={node.dimensions})\n"

        elif isinstance(node, MBooleanNode):
            left_tree  = self._visualize_node(node._left,  indent+4)
            right_tree = self._visualize_node(node._right, indent+4) 
            return (
                f"{indent_str}Boolean({node.oper.value})\n"
                f"{left_tree}\n"
                f"{right_tree}\n"
            )
        else:
           return f"{indent_str}Unknown Node"




    @property
    def root(self):
        return self._root



    @property
    def left(self):
        return self._left


    @property
    def right(self):
        return self._right




def post_traversal(root):
    result = []
    
    if root is None:
        return result
    
    node_info = {}
    if isinstance(root, MBooleanNode):
        result.extend(post_traversal(root.left))
        result.extend(post_traversal(root.right))
        node_info = {'node_type': 'boolean', 'oper_type': root.oper, "name": root.name, 'left': f'{root.left.name}', 'right': f'{root.right.name}'}
    elif isinstance(root, MPrimitiveNode):
        node_info = {'node_type': 'primitive', 'prim_type': root.prim_type, "name": root.name, "position": root.position, "rotation": root.rotation, "params": root.dimensions}

    result.append(node_info)

    return result
