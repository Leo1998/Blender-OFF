import os
import struct
import bpy
import mathutils
from bpy.props import (
    BoolProperty,
    EnumProperty,
    StringProperty,
    CollectionProperty,
)
from bpy_extras.io_utils import ImportHelper, ExportHelper, axis_conversion

bl_info = {
    "name": "OFF format",
    "description": "Import-Export OFF, supports Colors, UVs, and drag-and-drop.",
    "author": "Leonard Fricke",
    "version": (4, 2, 0),
    "blender": (4, 1, 0),
    "location": "File > Import-Export",
    "warning": "",
    "wiki_url": "",
    "category": "Import-Export"
}

def load_off(filepath, context, global_matrix, import_colors=True, import_uvs=True):
    is_binary = False
    with open(filepath, 'rb') as f:
        first_line = f.readline()
        if b'BINARY' in first_line.upper():
            is_binary = True

    if is_binary:
        with open(filepath, 'rb') as f:
            content = f.read()
            idx = content.find(b'\n') + 1
            
            header_tokens = first_line.decode('ascii', errors='ignore').split()
            header = header_tokens[0].upper()
            has_colors = 'C' in header
            has_uvs = 'ST' in header
            
            while idx < len(content) and content[idx:idx+1] == b'#':
                idx = content.find(b'\n', idx) + 1
                
            test_val = struct.unpack_from('<i', content, idx)[0]
            endian = '<' if 0 <= test_val < 100000000 else '>'
            
            vcount, fcount, _ = struct.unpack_from(endian + '3i', content, idx)
            idx += 12
            
            verts, vert_colors, vert_uvs = [], [], []
            for _ in range(vcount):
                verts.append(struct.unpack_from(endian + '3f', content, idx))
                idx += 12
                
                if has_colors and not has_uvs:
                    vert_colors.append(struct.unpack_from(endian + '4f', content, idx))
                    idx += 16
                elif has_uvs and not has_colors:
                    vert_uvs.append(struct.unpack_from(endian + '2f', content, idx))
                    idx += 8
                elif has_uvs and has_colors:
                    u, v, r, g, b, a = struct.unpack_from(endian + '6f', content, idx)
                    vert_uvs.append((u, v))
                    vert_colors.append((r, g, b, a))
                    idx += 24
                    
            facets = []
            for _ in range(fcount):
                nv = struct.unpack_from(endian + 'i', content, idx)[0]
                idx += 4
                face_indices = struct.unpack_from(endian + str(nv) + 'i', content, idx)
                facets.append(list(face_indices))
                idx += 4 * nv
    else:
        with open(filepath, 'r') as f:
            lines = [line.split('#')[0].strip() for line in f if line.split('#')[0].strip()]

        if not lines:
            return None

        tokens = lines[0].split()
        header = tokens[0].upper()
        has_colors = 'C' in header
        has_uvs = 'ST' in header

        data_idx = 1
        if len(tokens) >= 4:
            vcount, fcount = int(tokens[1]), int(tokens[2])
        else:
            counts = lines[data_idx].split()
            vcount, fcount = int(counts[0]), int(counts[1])
            data_idx += 1

        verts, vert_colors, vert_uvs = [], [], []

        for _ in range(vcount):
            bits = [float(x) for x in lines[data_idx].split()]
            verts.append((bits[0], bits[1], bits[2]))

            if has_colors and not has_uvs and len(bits) >= 6:
                r, g, b = bits[3:6]
                a = bits[6] if len(bits) > 6 else 1.0
                vert_colors.append((r, g, b, a))
            elif has_uvs and not has_colors and len(bits) >= 5:
                vert_uvs.append((bits[3], bits[4]))
            elif has_uvs and has_colors and len(bits) >= 7:
                vert_uvs.append((bits[3], bits[4]))
                r, g, b = bits[5:8]
                a = bits[8] if len(bits) > 8 else 1.0
                vert_colors.append((r, g, b, a))

            data_idx += 1

        facets = []
        for _ in range(fcount):
            splitted = lines[data_idx].split()
            n = int(splitted[0])
            ids = [int(idx) for idx in splitted[1:n+1]]
            facets.append(ids)
            data_idx += 1

    off_name = bpy.path.display_name_from_filepath(filepath)
    mesh = bpy.data.meshes.new(name=off_name)
    mesh.from_pydata(verts, [], facets)

    if vert_colors and any(max(c[:3]) > 1.0 for c in vert_colors):
        vert_colors = [(c[0]/255.0, c[1]/255.0, c[2]/255.0, c[3]/255.0 if c[3] > 1.0 else c[3]) for c in vert_colors]

    if import_colors and vert_colors:
        if hasattr(mesh, "color_attributes"): 
            color_layer = mesh.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
        else: 
            color_layer = mesh.vertex_colors.new(name="Col")
            
        for loop in mesh.loops:
            if loop.vertex_index < len(vert_colors):
                color_layer.data[loop.index].color = vert_colors[loop.vertex_index]

    if import_uvs and vert_uvs:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for loop in mesh.loops:
            if loop.vertex_index < len(vert_uvs):
                uv_layer.data[loop.index].uv = vert_uvs[loop.vertex_index]

    mesh.validate()
    mesh.update()

    obj = bpy.data.objects.new(mesh.name, mesh)
    obj.matrix_world = global_matrix
    context.collection.objects.link(obj)

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj


def save_off(filepath, context, global_matrix, use_colors, use_uvs, use_binary=False):
    obj = context.view_layer.objects.active
    if not obj or obj.type != 'MESH':
        return {'CANCELLED'}

    depsgraph = context.evaluated_depsgraph_get()
    mesh = obj.evaluated_get(depsgraph).to_mesh()
    mesh.transform(global_matrix @ obj.matrix_world)

    verts = mesh.vertices[:]
    
    vert_colors = {}
    if use_colors:
        color_data = None
        if hasattr(mesh, "color_attributes") and mesh.color_attributes:
            color_data = mesh.color_attributes.active.data
        elif hasattr(mesh, "vertex_colors") and mesh.vertex_colors:
            color_data = mesh.vertex_colors.active.data
            
        if color_data:
            for loop in mesh.loops:
                if loop.vertex_index not in vert_colors:
                    c = color_data[loop.index].color
                    vert_colors[loop.vertex_index] = (
                        int(c[0]*255), int(c[1]*255), int(c[2]*255), int(c[3]*255) if len(c)>3 else 255
                    )

    vert_uvs = {}
    if use_uvs and mesh.uv_layers.active:
        uv_data = mesh.uv_layers.active.data
        for loop in mesh.loops:
            if loop.vertex_index not in vert_uvs:
                vert_uvs[loop.vertex_index] = uv_data[loop.index].uv

    header = "OFF"
    if use_colors and vert_colors: header = "C" + header
    if use_uvs and vert_uvs: header = "ST" + header

    if use_binary:
        with open(filepath, 'wb') as f:
            f.write(f"{header} BINARY\n".encode('ascii'))
            f.write(struct.pack('<3i', len(verts), len(mesh.polygons), 0))

            for i, v in enumerate(verts):
                f.write(struct.pack('<3f', v.co.x, v.co.y, v.co.z))
                if use_uvs and vert_uvs:
                    uv = vert_uvs.get(i, (0.0, 0.0))
                    f.write(struct.pack('<2f', uv[0], uv[1]))
                if use_colors and vert_colors:
                    c = vert_colors.get(i, (255, 255, 255, 255))
                    f.write(struct.pack('<4f', c[0]/255.0, c[1]/255.0, c[2]/255.0, c[3]/255.0))

            for poly in mesh.polygons:
                f.write(struct.pack('<i', len(poly.vertices)))
                f.write(struct.pack(f'<{len(poly.vertices)}i', *poly.vertices))
    else:
        with open(filepath, 'w') as f:
            f.write(header + '\n')
            f.write(f"{len(verts)} {len(mesh.polygons)} 0\n")

            for i, v in enumerate(verts):
                line = f"{v.co.x:.6f} {v.co.y:.6f} {v.co.z:.6f}"
                if use_uvs and vert_uvs:
                    uv = vert_uvs.get(i, (0.0, 0.0))
                    line += f" {uv[0]:.6f} {uv[1]:.6f}"
                if use_colors and vert_colors:
                    c = vert_colors.get(i, (255, 255, 255, 255))
                    line += f" {c[0]} {c[1]} {c[2]} {c[3]}"
                f.write(line + '\n')

            for poly in mesh.polygons:
                f.write(f"{len(poly.vertices)} " + " ".join(str(v) for v in poly.vertices) + "\n")

    obj.to_mesh_clear()
    return {'FINISHED'}


class IMPORT_FH_off(bpy.types.FileHandler):
    bl_idname = "IMPORT_FH_off"
    bl_label = "File handler for OFF mesh import"
    bl_import_operator = "import_mesh.off"
    bl_file_extensions = ".off;.coff;.stoff"

    @classmethod
    def poll_drop(cls, context):
        return (context.area and context.area.type == 'VIEW_3D')


class ImportOFF(bpy.types.Operator, ImportHelper):
    bl_idname = "import_mesh.off"
    bl_label = "Import OFF Mesh"
    bl_options = {'UNDO', 'PRESET'}
    
    filename_ext = ".off"
    filter_glob: StringProperty(default="*.off;*.coff;*.stoff", options={'HIDDEN'})

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", options={'SKIP_SAVE'})
    
    files: CollectionProperty(
        name="File Path",
        type=bpy.types.OperatorFileListElement,
    )

    axis_forward: EnumProperty(
        name="Forward",
        items=(('X', "X Forward", ""), ('Y', "Y Forward", ""), ('Z', "Z Forward", ""),
               ('-X', "-X Forward", ""), ('-Y', "-Y Forward", ""), ('-Z', "-Z Forward", "")),
        default='Y',
    )
    axis_up: EnumProperty(
        name="Up",
        items=(('X', "X Up", ""), ('Y', "Y Up", ""), ('Z', "Z Up", ""),
               ('-X', "-X Up", ""), ('-Y', "-Y Up", ""), ('-Z', "-Z Up", "")),
        default='Z',
    )
    use_colors: BoolProperty(
        name="Import Colors",
        description="Import vertex colors if present",
        default=True,
    )
    use_uvs: BoolProperty(
        name="Import UVs",
        description="Import Texture Coordinates if present",
        default=True,
    )

    def invoke(self, context, event):
        if self.filepath:
            return self.execute(context)
        
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        global_matrix = axis_conversion(
            from_forward=self.axis_forward,
            from_up=self.axis_up,
        ).to_4x4()

        if self.files:
            folder = os.path.dirname(self.filepath)
            for file_elem in self.files:
                path = os.path.join(folder, file_elem.name)
                load_off(path, context, global_matrix, self.use_colors, self.use_uvs)
        else:
            load_off(self.filepath, context, global_matrix, self.use_colors, self.use_uvs)

        return {'FINISHED'}


class ExportOFF(bpy.types.Operator, ExportHelper):
    bl_idname = "export_mesh.off"
    bl_label = "Export OFF Mesh"
    
    filename_ext = ".off"
    filter_glob: StringProperty(default="*.off", options={'HIDDEN'})
    check_extension = True

    axis_forward: EnumProperty(
        name="Forward",
        items=(('X', "X Forward", ""), ('Y', "Y Forward", ""), ('Z', "Z Forward", ""),
               ('-X', "-X Forward", ""), ('-Y', "-Y Forward", ""), ('-Z', "-Z Forward", "")),
        default='Y',
    )
    axis_up: EnumProperty(
        name="Up",
        items=(('X', "X Up", ""), ('Y', "Y Up", ""), ('Z', "Z Up", ""),
               ('-X', "-X Up", ""), ('-Y', "-Y Up", ""), ('-Z', "-Z Up", "")),
        default='Z',
    )
    use_colors: BoolProperty(
        name="Vertex Colors",
        description="Export the active vertex color layer",
        default=True,
    )
    use_uvs: BoolProperty(
        name="Texture Coordinates",
        description="Export the active UV layer",
        default=True,
    )
    use_binary: BoolProperty(
        name="Binary",
        description="Export as Binary OFF",
        default=False,
    )

    def execute(self, context):
        global_matrix = axis_conversion(
            to_forward=self.axis_forward,
            to_up=self.axis_up,
        ).to_4x4()
        
        return save_off(self.filepath, context, global_matrix, self.use_colors, self.use_uvs, self.use_binary)


def menu_func_import(self, context):
    self.layout.operator(ImportOFF.bl_idname, text="OFF Mesh (.off)")

def menu_func_export(self, context):
    self.layout.operator(ExportOFF.bl_idname, text="OFF Mesh (.off)")

classes = (
    IMPORT_FH_off,
    ImportOFF,
    ExportOFF,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()