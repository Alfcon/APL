"""Standalone STEP -> per-component top-down PNG renderer.

Runs in a Python environment with pythonocc-core installed (see
find_step_render_python in parser.py). Invoked as a subprocess by the main app.

Usage:
    python step_render_worker.py <step_path> <out_dir> <components_json> [tile_px]

components_json is a file containing a list of objects with at least:
    {"designator", "x", "y", "width_mm", "height_mm"}

The STEP assembly is read through XCAF so each component lives as its own named
node (the Altium designator: "R27", "IC1", ...). For every requested designator
we display *only* that node's geometry, frame the orthographic top-down camera
on its bounding box, and dump a tightly-cropped PNG. Designators with no 3D body
in the STEP (test points, mounting holes, power flags) are simply skipped.

Prints a single line of JSON to stdout on success:
    {"thumbs": {"R1": "/abs/path/R1.png", ...}}
"""
import os
import re
import sys
import json

from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool
from OCC.Core.XCAFPrs import XCAFPrs_AISObject
from OCC.Core.TDF import TDF_LabelSequence, TDF_Label
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Display.OCCViewer import Viewer3d
from OCC.Core.V3d import V3d_Zpos
from OCC.Core.Graphic3d import Graphic3d_Camera

_SAFE_RE = re.compile(r'[^A-Za-z0-9._-]')

MARGIN_MM = 0.3


def _safe_name(designator):
    name = _SAFE_RE.sub('_', str(designator).strip())
    return name or 'unnamed'


def main():
    step_path = sys.argv[1]
    out_dir = sys.argv[2]
    components_json = sys.argv[3]
    tile_px = int(sys.argv[4]) if len(sys.argv) > 4 else 512

    os.makedirs(out_dir, exist_ok=True)

    with open(components_json, 'r') as f:
        components = json.load(f)
    wanted = {str(c['designator']).strip() for c in components if c.get('designator')}

    doc = TDocStd_Document("adcs-step")
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(step_path) != IFSelect_RetDone:
        print(json.dumps({"thumbs": {}, "error": "STEP read failed"}))
        return
    reader.Transfer(doc)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool(doc.Main())

    viewer = Viewer3d()
    viewer.Create()
    viewer.SetSize(tile_px, tile_px)
    viewer.SetModeShaded()
    viewer.set_bg_gradient_color([255, 255, 255], [255, 255, 255])
    context = viewer.Context
    view = viewer.View
    view.Camera().SetProjectionType(Graphic3d_Camera.Projection_Orthographic)

    thumbs = {}

    def _render(designator, label):
        """Display only this node, frame the top-down camera on it, dump a PNG."""
        shape = shape_tool.GetShape(label)
        box = Bnd_Box()
        brepbndlib.Add(shape, box)
        if box.IsVoid():
            return
        xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
        frame = Bnd_Box()
        frame.Update(xmin - MARGIN_MM, ymin - MARGIN_MM, zmin - MARGIN_MM,
                     xmax + MARGIN_MM, ymax + MARGIN_MM, zmax + MARGIN_MM)

        ais = XCAFPrs_AISObject(label)
        context.Display(ais, False)
        view.SetProj(V3d_Zpos)
        view.FitAll(frame, 0.01)
        viewer.Repaint()

        out_png = os.path.join(out_dir, _safe_name(designator) + '.png')
        view.Dump(out_png)
        context.Remove(ais, False)
        if os.path.exists(out_png):
            thumbs[designator] = out_png

    # Walk the assembly tree. A node is a component when its referred-shape name
    # matches a requested designator; we render it inline and stop descending
    # that branch. Rendering inside the walk keeps the TDF_LabelSequence holding
    # each label alive until its shape has been read.
    def _walk(label):
        comps = TDF_LabelSequence()
        shape_tool.GetComponents(label, comps)
        for i in range(comps.Length()):
            child = comps.Value(i + 1)
            if not shape_tool.IsReference(child):
                continue
            ref = TDF_Label()
            shape_tool.GetReferredShape(child, ref)
            name = ref.GetLabelName()
            if name in wanted and name not in thumbs:
                _render(name, child)
            elif shape_tool.IsAssembly(ref):
                _walk(ref)

    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    for i in range(free.Length()):
        _walk(free.Value(i + 1))

    print(json.dumps({"thumbs": thumbs}))


if __name__ == "__main__":
    main()
