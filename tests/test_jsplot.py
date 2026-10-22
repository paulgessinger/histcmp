"""The optional canvas backend preserves Python-prepared drawing geometry."""
import base64
import gzip
import json

import hist
import numpy as np
import pytest
from matplotlib import pyplot
from matplotlib.path import Path
from matplotlib.transforms import Affine2D, Bbox

from histcmp.jsplot import CanvasRenderer, JSPlot
from histcmp.plot import PlotSpec, render_plots


def test_transforms_clipping_and_alpha():
    renderer = CanvasRenderer(100, 100)
    gc = renderer.new_gc()
    gc.set_clip_rectangle(Bbox.from_bounds(1, 2, 30, 40))
    gc.set_alpha(0.3)
    gc.set_linewidth(2)
    path = Path([(0, 0), (1, 1)])
    renderer.draw_path(gc, path, Affine2D().scale(3).translate(10, 20), (1, 0, 0, 1))
    renderer.draw_path(gc, path, Affine2D().translate(5, 6), (1, 0, 0, 1))
    assert len(renderer.paths) == 1
    assert len(renderer.styles) == 1
    assert renderer.commands[0][2] == [3, 0, 0, 3, 10, 20]
    assert renderer.styles[0][0] == "rgba(255,0,0,0.3)"
    assert renderer.styles[0][2] == 2  # Stroke width does not scale with the path.
    assert renderer.styles[0][7] == [1, 2, 30, 40]


@pytest.mark.parametrize("kind,renderer", [
    ("1d", None), ("eff", None), ("2d", None),
    ("3d", "scatter"), ("3d", "voxel"),
])
def test_canvas_payloads(tmp_path, kind, renderer):
    ndim = {"1d": 1, "eff": 1, "2d": 2, "3d": 3}[kind]
    a = hist.Hist(*(hist.axis.Regular(4, -2, 2, name=n)
                    for n in "xyz"[:ndim]), storage=hist.storage.Weight(),
                  name=r"Test $\eta$", label="entries")
    a.view().value[...] = 0.6 if kind == "eff" else 4
    a.view().variance[...] = 0.01 if kind == "eff" else 4
    b = a.copy()
    # Empty denominators exercise masked/nonfinite comparison bins.
    b.view().value.flat[0] = 0
    err = np.full((2, 4), 0.1) if kind == "eff" else None
    spec = PlotSpec(kind, a, b, err_a=err, err_b=err, renderer=renderer)
    before = pyplot.get_fignums()
    plots = render_plots([spec], "key", "a", "b", tmp_path, js_plots=True)
    assert pyplot.get_fignums() == before
    assert not list(tmp_path.iterdir())
    assert len(plots) == (1 if ndim == 1 else 3)
    for plot in plots:
        assert isinstance(plot, JSPlot)
        data = json.loads(gzip.decompress(base64.b64decode(plot.payload)))
        assert data["width"] == plot.width
        assert data["height"] == plot.height
        assert data["commands"]
        assert data["paths"]
        for path, style, matrix in data["commands"]:
            assert 0 <= path < len(data["paths"])
            assert 0 <= style < len(data["styles"])
            assert np.isfinite(matrix).all()
