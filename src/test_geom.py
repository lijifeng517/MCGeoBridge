import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Rectangle, Ellipse, PathPatch
from matplotlib.path import Path
import matplotlib.lines as mlines

class GeometryNode:
    """Geometry tree node class"""
    def __init__(self, name, node_type, params=None, op=None, left=None, right=None):
        self.name = name        # Node name
        self.node_type = node_type  # 'primitive' or 'boolean'
        self.params = params    # Primitive parameters
        self.op = op            # Boolean operation type
        self.left = left        # Left subtree
        self.right = right      # Right subtree

def plot_geometry_tree(root, ax=None):
    """Visualize geometry boolean tree"""
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.set_aspect('equal')
        ax.axis('off')
    
    # Calculate max tree depth
    max_depth = calculate_max_depth(root)
    
    # Recursively plot tree
    _plot_node(root, ax, x=0.5, y=0.9, width=1.0, depth=0, max_depth=max_depth)
    
    # Add legend
    _add_legend(ax)
    
    #plt.title('Geometry Boolean Tree Visualization', fontsize=16)
    plt.tight_layout()
    return ax

def calculate_max_depth(node):
    """Calculate max tree depth"""
    if node is None:
        return 0
    left_depth = calculate_max_depth(node.left)
    right_depth = calculate_max_depth(node.right)
    return max(left_depth, right_depth) + 1

def _plot_node(node, ax, x, y, width, depth, max_depth):
    """Recursively plot node and connections"""
    if node is None:
        return
    
    # Calculate vertical spacing
    vertical_spacing = 0.8 / max_depth
    
    # Draw current node
    _draw_node(node, ax, x, y)
    
    # Calculate child positions
    if node.left:
        left_x = x - width/4
        left_y = y - vertical_spacing
        # Draw connection line
        ax.plot([x, left_x], [y, left_y], 'k-', lw=1.5, alpha=0.7)
        # Recursively plot left subtree
        _plot_node(node.left, ax, left_x, left_y, width/2, depth+1, max_depth)
    
    if node.right:
        right_x = x + width/4
        right_y = y - vertical_spacing
        # Draw connection line
        ax.plot([x, right_x], [y, right_y], 'k-', lw=1.5, alpha=0.7)
        # Recursively plot right subtree
        _plot_node(node.right, ax, right_x, right_y, width/2, depth+1, max_depth)

def _draw_node(node, ax, x, y):
    """Draw a single node"""
    node_size = 0.1  # Node size
    
    if node.node_type == 'primitive':
        # Primitive geometry node
        geom_type = node.params['type']
        
        if geom_type == 'sphere':
            # Sphere - 3D sphere representation
            # Draw sphere with shading effect
            circle = Circle((x, y), node_size/1.5, 
                           facecolor='red', edgecolor='black', alpha=0.8)
            ax.add_patch(circle)
            
            # Add highlight to make it look spherical
            highlight = Ellipse((x - node_size/10*0.0, y + node_size/2), 
                               node_size/3, node_size/6,
                               facecolor='white', alpha=0.3, edgecolor='none')
            ax.add_patch(highlight)
            
            ax.text(x, y, 'Sph', ha='center', va='center', fontsize=16, color='white')
            
        elif geom_type == 'cylinder':
            # Cylinder - 3D representation
            # Main body
            rect = Rectangle((x-node_size/2, y-node_size*1/2), node_size, node_size*3/3,
                            facecolor='green', edgecolor='black', alpha=0.8)
            ax.add_patch(rect)
            
            # Top ellipse
            top_ellipse = Ellipse((x, y + node_size*1/2), node_size, node_size/3,
                                 facecolor='darkgreen', edgecolor='black', alpha=0.8)
            ax.add_patch(top_ellipse)
            
            ax.text(x, y, 'Cyl', ha='center', va='center', fontsize=16, color='white')
            
        elif geom_type == 'box':
            # Box - 3D representation
            # Front face
            rect = Rectangle((x-node_size/2, y-node_size/2), node_size, node_size,
                            facecolor='blue', edgecolor='black', alpha=0.8)
            ax.add_patch(rect)
            
            # Side face
            side = plt.Polygon([(x+node_size/2, y-node_size/2),
                               (x+node_size/2, y+node_size/2),
                               (x+node_size/2.5, y+node_size/2.5),
                               (x+node_size/2.5, y-node_size/2.5)],
                              facecolor='darkblue', edgecolor='black', alpha=0.8)
            ax.add_patch(side)
            
            # Top face
            top = plt.Polygon([(x-node_size/2, y+node_size/2),
                              (x+node_size/2, y+node_size/2),
                              (x+node_size/2.5, y+node_size/2.5),
                              (x-node_size/2.5, y+node_size/2.5)],
                             facecolor='lightblue', edgecolor='black', alpha=0.8)
            ax.add_patch(top)
            
            ax.text(x, y, 'Box', ha='center', va='center', fontsize=16, color='white')
            
        elif geom_type == 'cone':
            # Cone - 3D representation
            # Base
            base = Ellipse((x, y-node_size/3), node_size, node_size/2,
                          facecolor='purple', edgecolor='black', alpha=0.8)
            ax.add_patch(base)
            
            # Body
            triangle = plt.Polygon([(x, y+node_size/3), 
                                   (x-node_size/2, y-node_size/3),
                                   (x+node_size/2, y-node_size/3)], 
                                  facecolor='purple', edgecolor='black', alpha=0.8)
            ax.add_patch(triangle)
            
            ax.text(x, y, 'Cone', ha='center', va='center', fontsize=16, color='white')
            
    else:
        # Boolean operation node - use diamond shape
        # Create diamond vertices
        verts = [
            (x, y + node_size/1.5),  # top
            (x - node_size/1.0, y),  # left
            (x, y - node_size/1.5),  # bottom
            (x + node_size/1.0, y),  # right
            (x, y + node_size/1.5)   # back to top
        ]
        
        codes = [Path.MOVETO, Path.LINETO, Path.LINETO, Path.LINETO, Path.CLOSEPOLY]
        path = Path(verts, codes)
        
        if node.op == 'union':
            patch = PathPatch(path, facecolor='gold', edgecolor='black', alpha=0.8)
            ax.add_patch(patch)
            ax.text(x, y, 'Union', ha='center', va='center', fontsize=16, color='blue')
            
        elif node.op == 'intersection':
            patch = PathPatch(path, facecolor='orange', edgecolor='black', alpha=0.8)
            ax.add_patch(patch)
            ax.text(x, y, 'Intsect', ha='center', va='center', fontsize=16, color='blue')
            
        elif node.op == 'difference':
            patch = PathPatch(path, facecolor='cyan', edgecolor='black', alpha=0.8)
            ax.add_patch(patch)
            ax.text(x, y, 'Subtract', ha='center', va='center', fontsize=16, color='blue')
    
    # Add node name label
    ax.text(x, y + node_size*0.8, node.name, 
            ha='center', va='bottom', fontsize=18, color='darkblue')

def _add_legend(ax):
    """Add English legend"""
    legend_elements = [
        mlines.Line2D([0], [0], marker='o', color='w', markerfacecolor='red', 
                      markersize=10, label='Sphere'),
        mlines.Line2D([0], [0], marker='s', color='w', markerfacecolor='blue', 
                      markersize=10, label='Box'),
        mlines.Line2D([0], [0], marker='s', color='w', markerfacecolor='green', 
                      markersize=10, label='Cylinder'),
        mlines.Line2D([0], [0], marker='^', color='w', markerfacecolor='purple', 
                      markersize=10, label='Cone'),
        mlines.Line2D([0], [0], marker='d', color='w', markerfacecolor='gold', 
                      markersize=10, label='Union (∪)'),
        mlines.Line2D([0], [0], marker='d', color='w', markerfacecolor='orange', 
                      markersize=10, label='Intersection (∩)'),
        mlines.Line2D([0], [0], marker='d', color='w', markerfacecolor='cyan', 
                      markersize=10, label='Difference (-)')
    ]
    
    #ax.legend(handles=legend_elements, loc='upper right', fontsize=16)

# Example usage
if __name__ == "__main__":
    # Create geometry boolean tree
    sphere = GeometryNode(
        name="Sol_S1", 
        node_type="primitive",
        params={"type": "sphere", "radius": 5.0}
    )
    
    cylinder = GeometryNode(
        name="Sol_S2", 
        node_type="primitive",
        params={"type": "cylinder", "radius": 3.0, "height": 15.0}
    )
    
    box = GeometryNode(
        name="Sol_S3", 
        node_type="primitive",
        params={"type": "box", "width": 8.0, "height": 8.0, "depth": 8.0}
    )
    
    # Boolean operation node (Cylinder - Sphere)
    diff_node = GeometryNode(
        name="Sol_S4", 
        node_type="boolean",
        op="difference",
        left=cylinder,
        right=sphere
    )
    
    # Root node (Difference ∪ Box)
    root_node = GeometryNode(
        name="Sol_S5", 
        node_type="boolean",
        op="union",
        left=diff_node,
        right=box
    )
    
    # Visualize geometry tree
    plot_geometry_tree(root_node)
    plt.savefig('geometry_tree.png', dpi=300, bbox_inches='tight')
    plt.show()
