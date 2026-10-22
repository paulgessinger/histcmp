"""Exercise SVG export without requiring PyROOT."""

import base64
import io
import xml.etree.ElementTree as ET

import hist
import numpy as np
from PIL import Image
import pytest
from matplotlib import pyplot

from histcmp.plot import PlotSpec, render_plots


@pytest.mark.parametrize("kind,renderer", [
    ("1d", None), ("eff", None), ("2d", None),
    ("3d", "scatter"), ("3d", "voxel"),
])
def test_svg_vector_labels_and_raster_data(tmp_path, kind, renderer):
    ndim = {"1d": 1, "eff": 1, "2d": 2, "3d": 3}[kind]
    a = hist.Hist(*(hist.axis.Regular(4, -2, 2, name=n)
                    for n in "xyz"[:ndim]), storage=hist.storage.Weight(),
                  name="Vector labels", label="entries")
    a.view().value[...] = 0.6 if kind == "eff" else 4
    a.view().variance[...] = 0.01 if kind == "eff" else 4
    b = a.copy()
    err = np.full((2, 4), 0.1) if kind == "eff" else None
    spec = PlotSpec(kind, a, b, err_a=err, err_b=err, renderer=renderer)
    before = pyplot.get_fignums()
    paths = render_plots([spec], "directory/key", "monitored", "reference", tmp_path)
    assert pyplot.get_fignums() == before
    assert len(paths) == (1 if ndim == 1 else 3)
    ns = {"s": "http://www.w3.org/2000/svg"}
    for path in paths:
        assert path.suffix == ".svg"
        root = ET.parse(path).getroot()
        images = root.findall(".//s:image", ns)
        assert bool(images) == (ndim > 1)
        # Default SVG glyph paths keep fonts portable and sharp when zoomed.
        labels = [g for g in root.findall(".//s:g", ns)
                  if g.get("id", "").startswith("text_")]
        assert labels
        assert any(g.findall(".//s:use", ns) for g in labels)
        rasters = []
        for element in images:
            uri = element.get("{http://www.w3.org/1999/xlink}href")
            assert uri.startswith("data:image/png;base64,")
            image = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
            assert image.width > 0 and image.height > 0
            rasters.append(image)
        if ndim == 3:
            # The data layer is cropped to the scatter/voxels, not a raster
            # screenshot of the entire figure (720 x 600 at 120 dpi).
            assert any(image.width > 100 for image in rasters)
            assert all(float(e.get("width")) < 432 for e in images)
