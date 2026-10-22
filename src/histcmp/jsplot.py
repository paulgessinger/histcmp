"""Experimental rendering-only canvas backend.

Matplotlib computes layout, statistics, projections and glyph outlines in Python.
The browser replays paths; it never recalculates histogram quantities. Payloads
are compressed per figure so the report can decode only visible plots.
"""

import base64
from dataclasses import dataclass
import gzip
import json

import numpy as np
from matplotlib.backend_bases import RendererBase
from matplotlib.path import Path


@dataclass(frozen=True)
class JSPlot:
    payload: str
    width: float
    height: float


class CanvasRenderer(RendererBase):
    def __init__(self, width, height):
        super().__init__()
        self.width, self.height = width, height
        self.paths = []
        self.styles = []
        self.commands = []
        self._paths = {}
        self._styles = {}

    def get_canvas_width_height(self):
        return self.width, self.height

    def flipy(self):
        return False

    def _path(self, path):
        key = (path.vertices.tobytes(), None if path.codes is None else path.codes.tobytes())
        if key not in self._paths:
            parts = []
            letters = {Path.MOVETO: "M", Path.LINETO: "L", Path.CURVE3: "Q", Path.CURVE4: "C"}
            for vertices, code in path.iter_segments(simplify=False):
                if code == Path.CLOSEPOLY:
                    parts.append("Z")
                elif code in letters:
                    parts.append(letters[code] + " ".join(str(float(v)) for v in vertices))
            self._paths[key] = len(self.paths)
            self.paths.append(" ".join(parts))
        return self._paths[key]

    @staticmethod
    def _matrix(transform):
        m = transform.get_matrix()
        return [float(m[0, 0]), float(m[1, 0]), float(m[0, 1]),
                float(m[1, 1]), float(m[0, 2]), float(m[1, 2])]

    def draw_path(self, gc, path, transform, rgbFace=None):
        if not transform.is_affine:
            path = transform.transform_path(path)
            from matplotlib.transforms import IdentityTransform
            transform = IdentityTransform()
        matrix = self._matrix(transform)
        if not np.isfinite(matrix).all():
            return
        clip = gc.get_clip_rectangle()
        clip_path, clip_transform = gc.get_clip_path()
        offset, dashes = gc.get_dashes()

        def rgba(color):
            if color is None:
                return None
            r, g, b, *alpha = color
            a = gc.get_alpha() if gc.get_forced_alpha() else (alpha[0] if alpha else 1)
            return f"rgba({r * 255},{g * 255},{b * 255},{a})"

        style = [rgba(rgbFace), rgba(gc.get_rgb()), gc.get_linewidth(),
                 gc.get_capstyle(), gc.get_joinstyle(), offset,
                 [] if dashes is None else list(dashes),
                 None if clip is None else list(clip.bounds),
                 None if clip_path is None else [self._path(clip_path), self._matrix(clip_transform)]]
        key = json.dumps(style, separators=(",", ":"))
        if key not in self._styles:
            self._styles[key] = len(self.styles)
            self.styles.append(style)
        self.commands.append([self._path(path), self._styles[key], matrix])

    def draw_text(self, gc, x, y, s, prop, angle, ismath=False, mtext=None):
        self._draw_text_as_path(gc, x, y, s, prop, angle, ismath, mtext)


def render_canvas(fig) -> JSPlot:
    original_dpi = fig.dpi
    try:
        fig.set_dpi(72)
        width, height = fig.get_size_inches() * 72
        renderer = CanvasRenderer(float(width), float(height))
        fig.draw(renderer)
        data = {"width": float(width), "height": float(height),
                "paths": renderer.paths, "styles": renderer.styles,
                "commands": renderer.commands}
        raw = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
        payload = base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")
        return JSPlot(payload, float(width), float(height))
    finally:
        fig.set_dpi(original_dpi)
