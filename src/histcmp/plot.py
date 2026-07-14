import warnings
import io
import re
import base64
import dataclasses
import urllib.parse
from typing import Any, Optional

#  from abc import ABC, abstractmethod, abstractproperty
#  from pathlib import Path
import numpy
import mplhep

import hist
import rich
import matplotlib.cm
import matplotlib.colors
from matplotlib import pyplot

from histcmp.console import warn

pyplot.rcParams.update(
    {
        "xtick.top": True,
        "ytick.right": True,
        "xtick.direction": "in",
        "ytick.direction": "in",
    }
)


#  class Plot(ABC):
#  @abstractmethod
#  def to_html(self) -> str:
#  raise NotImplementedError()


#  class FilePlot(Plot):
#  def __init__(self, path: Path):
#  self.path = path

#  def to_html(self) -> str:
#  return f'<img src="{self.path}"/>'


def sanitize_name(s):
    return (s or "").replace(r"\GT", r">").replace(r"\LT", "<")


def _two_panel_figure():
    return pyplot.subplots(
        2, 1, gridspec_kw=dict(height_ratios=[2, 0.5], hspace=0.05)
    )


def _finish_two_panel(fig, ax, rax, a):
    ax.set_ylabel(a.label)
    ax.set_xlabel("")
    ax.set_xticklabels([])
    rax.set_xlim(*ax.get_xlim())
    ax.set_title(sanitize_name(a.name))
    fig.align_ylabels()
    #  fig.tight_layout()
    fig.subplots_adjust(left=0.14, right=0.95, top=0.9, bottom=0.1)


def plot_ratio_eff(a, a_err, b, b_err, label_a, label_b):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, (ax, rax) = _two_panel_figure()

        a_err = numpy.maximum(0, a_err)
        b_err = numpy.maximum(0, b_err)

        mplhep.histplot(a.values(), a.axes[0].edges, yerr=a_err, ax=ax, label=label_a)
        mplhep.histplot(b.values(), b.axes[0].edges, yerr=b_err, ax=ax, label=label_b)

        ratio = a.values() / b.values()

        a_err = 0.5 * (a_err[0] + a_err[1])
        b_err = 0.5 * (b_err[0] + b_err[1])

        r_err = numpy.sqrt(
            (a_err / b.values()) ** 2 + (a.values() / b.values() ** 2 * b_err) ** 2
        )

        rax.axhline(1, ls="--", color="black")
        rax.errorbar(
            b.axes[0].centers,
            ratio,
            yerr=r_err,
            marker="o",
            markersize=2,
            ls="none",
            color="black",
        )

    rax.set_xlabel(a.axes[0].name)
    rax.set_ylabel(f"{label_a} / {label_b}")

    ax.legend()
    ax.set_ylim(top=1.015)
    _finish_two_panel(fig, ax, rax, a)

    return fig, (ax, rax)


def plot_ratio(a: hist.Hist, b: hist.Hist, label_a: str, label_b: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        fig, (ax, rax) = _two_panel_figure()

        try:
            ratio = a.values() / b.values()
            ratio = ratio[~numpy.isnan(ratio) & numpy.isfinite(ratio)]
            #  print(a.values())
            #  print(b.values())
            #  print(ratio)
            if len(ratio) > 0:
                ymin, ymax = numpy.min(ratio), numpy.max(ratio)
            else:
                ymin, ymax = 0.5, 2

            yrange = ymax - ymin
            ymin -= yrange * 0.2
            ymax += yrange * 0.2

            #  ymin = 0.1
            #  ymax = 3

            #  print(ymin, ymax)
            main_ax_artists, subplot_ax_artists = a.plot_ratio(
                b,
                ax_dict=dict(main_ax=ax, ratio_ax=rax),
                rp_ylabel=f"{label_a} / {label_b}",
                rp_num_label=label_a,
                rp_denom_label=label_b,
                rp_uncert_draw_type="line",  # line or bar
                rp_uncertainty_type="poisson",
                rp_ylim=(ymin, ymax),
            )
            markers, _, _ = subplot_ax_artists.errorbar.lines
            markers.set_markersize(2)
        except ValueError:
            raise
            #  ax.clear()
            #  rax.clear()
            #  a.plot(ax=ax)
            #  b.plot(ax=ax)

    _finish_two_panel(fig, ax, rax, a)

    return fig, (ax, rax)


def plot_1d(
    a: hist.Hist, b: hist.Hist, label_a: str, label_b: str, comparison: str = "ratio"
):
    if comparison == "ratio":
        return plot_ratio(a, b, label_a, label_b)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        fig, (ax, rax) = _two_panel_figure()

        for h, label in [(a, label_a), (b, label_b)]:
            mplhep.histplot(
                h.values(),
                h.axes[0].edges,
                yerr=numpy.sqrt(h.variances()),
                ax=ax,
                label=label,
            )

        data = _comparison_values(a, b, comparison, label_a, label_b)
        m = ~numpy.ma.getmaskarray(data.values)

        rax.axhline(data.center, ls="--", color="black")
        rax.errorbar(
            a.axes[0].centers[m],
            numpy.asarray(data.values[m]),
            yerr=data.err[m] if data.err is not None else None,
            marker="o",
            markersize=2,
            ls="none",
            color="black",
        )

    rax.set_xlabel(a.axes[0].name)
    rax.set_ylabel(data.short_label)

    ax.legend()
    _finish_two_panel(fig, ax, rax, a)

    return fig, (ax, rax)


def _diverging_norm(
    values: numpy.ndarray, center: float
) -> matplotlib.colors.TwoSlopeNorm:
    """
    Diverging norm with a symmetric range around the given center. The range
    uses a robust percentile so single noisy low-statistics bins don't wash
    out the color scale, and is clamped to a minimum so identical histograms
    don't produce a degenerate norm.
    """
    if len(values) > 0:
        dev = numpy.percentile(numpy.abs(values - center), 98)
    else:
        dev = 0.0
    dev = max(dev, 1e-3)
    return matplotlib.colors.TwoSlopeNorm(
        vcenter=center, vmin=center - dev, vmax=center + dev
    )


@dataclasses.dataclass(frozen=True)
class ComparisonData:
    """Per-bin comparison metric between two histograms."""

    # metric values, undefined bins masked
    values: numpy.ma.MaskedArray
    # per-bin error of the metric, if it has a meaningful one
    err: Optional[numpy.ndarray]
    # neutral value of the metric ("no difference")
    center: float
    # diverging color norm centered on the neutral value
    norm: matplotlib.colors.TwoSlopeNorm
    label: str
    # short form that fits as a 1D axis label
    short_label: str


def _comparison_values(
    a: hist.Hist, b: hist.Hist, comparison: str, label_a: str, label_b: str
) -> ComparisonData:
    va = a.values()
    vb = b.values()
    err = None

    with numpy.errstate(divide="ignore", invalid="ignore"):
        if comparison == "ratio":
            values = numpy.ma.masked_invalid(va / vb)
            center = 1.0
            label = short_label = f"{label_a} / {label_b}"
        elif comparison == "residual":
            values = numpy.ma.masked_where((va == 0) & (vb == 0), va - vb)
            center = 0.0
            label = short_label = f"{label_a} - {label_b}"
            err = numpy.sqrt(a.variances() + b.variances())
        elif comparison == "pull":
            sigma = numpy.sqrt(a.variances() + b.variances())
            values = numpy.ma.masked_where(sigma == 0, (va - vb) / sigma)
            center = 0.0
            label = f"pull ({label_a} vs {label_b})"
            short_label = "pull"
        elif comparison == "asymmetry":
            values = numpy.ma.masked_where(va + vb == 0, (va - vb) / (va + vb))
            center = 0.0
            label = f"asymmetry ({label_a} vs {label_b})"
            short_label = "asymmetry"
        else:
            raise ValueError(f"Unknown comparison metric {comparison!r}")

    norm = _diverging_norm(values.compressed(), center)
    return ComparisonData(values, err, center, norm, label, short_label)


def _value_panels(va, vb, label_a, label_b):
    return [("_monitored", va, label_a), ("_reference", vb, label_b)]


def _new_2d_panel(a: hist.Hist, title: str):
    fig, ax = pyplot.subplots(figsize=(6, 4.5), constrained_layout=True)
    ax.set_xlabel(a.axes[0].name)
    ax.set_ylabel(a.axes[1].name)
    ax.set_title(title)
    fig.suptitle(sanitize_name(a.name))
    return fig, ax


def plot_2d(
    a: hist.Hist, b: hist.Hist, label_a: str, label_b: str, comparison: str = "ratio"
):
    """
    Returns a list of (suffix, figure) pairs: one figure each for the
    monitored and reference maps (on a shared color scale) and the
    comparison metric map.
    """
    xe = a.axes[0].edges
    ye = a.axes[1].edges
    va = a.values()
    vb = b.values()

    vmax = max(va.max(), vb.max())
    vmin = min(va.min(), vb.min())

    figs = []

    for suffix, v, label in _value_panels(va, vb, label_a, label_b):
        fig, ax = _new_2d_panel(a, label)
        # rasterize: an SVG with one path per bin explodes the report size
        pcm = ax.pcolormesh(
            xe,
            ye,
            numpy.ma.masked_equal(v, 0).T,
            vmin=vmin,
            vmax=vmax,
            rasterized=True,
        )
        fig.colorbar(pcm, ax=ax, label=a.label or "entries")
        figs.append((suffix, fig))

    data = _comparison_values(a, b, comparison, label_a, label_b)
    fig, ax = _new_2d_panel(a, data.label)
    pcm = ax.pcolormesh(
        xe, ye, data.values.T, norm=data.norm, cmap="RdBu_r", rasterized=True
    )
    fig.colorbar(pcm, ax=ax)
    figs.append((f"_{comparison}", fig))

    return figs


def _new_3d_panel(a: hist.Hist, title: str):
    fig = pyplot.figure(figsize=(6, 5))
    ax = fig.add_subplot(projection="3d")
    ax.set_xlabel(a.axes[0].name)
    ax.set_ylabel(a.axes[1].name)
    ax.set_zlabel(a.axes[2].name)
    ax.set_title(title)
    fig.suptitle(sanitize_name(a.name))
    return fig, ax


def plot_3d_scatter(
    a: hist.Hist, b: hist.Hist, label_a: str, label_b: str, comparison: str = "ratio"
):
    """
    Returns a list of (suffix, figure) pairs, like plot_2d.
    """
    cx, cy, cz = numpy.meshgrid(*(ax.centers for ax in a.axes), indexing="ij")
    va = a.values()
    vb = b.values()
    vmax = max(va.max(), vb.max(), 1e-9)
    vmin = min(va.min(), vb.min())

    max_marker_area = 60.0  # pt^2
    min_marker_area = 1.0  # keep low bins visible

    def marker_area(v):
        return numpy.clip(
            max_marker_area * numpy.abs(v) / vmax, min_marker_area, None
        )

    figs = []

    for suffix, v, label in _value_panels(va, vb, label_a, label_b):
        fig, ax = _new_3d_panel(a, label)
        m = v != 0
        sc = ax.scatter(
            cx[m],
            cy[m],
            cz[m],
            s=marker_area(v[m]),
            c=v[m],
            vmin=vmin,
            vmax=vmax,
            alpha=0.5,
        )
        fig.colorbar(sc, ax=ax, label=a.label or "entries", shrink=0.7, pad=0.1)
        figs.append((suffix, fig))

    # comparison panel: marker size shows the reference statistics, color the
    # deviation of the comparison metric from its neutral value
    data = _comparison_values(a, b, comparison, label_a, label_b)
    m = ~numpy.ma.getmaskarray(data.values)
    fig, ax = _new_3d_panel(a, data.label)
    sc = ax.scatter(
        cx[m],
        cy[m],
        cz[m],
        s=marker_area(vb[m]),
        c=numpy.asarray(data.values[m]),
        cmap="RdBu_r",
        norm=data.norm,
        alpha=0.7,
    )
    fig.colorbar(sc, ax=ax, label=data.label, shrink=0.7, pad=0.1)
    figs.append((f"_{comparison}", fig))

    return figs


#  Axes3D.voxels builds up to 6 polygons per filled bin and becomes very slow
#  and very large beyond this
MAX_VOXELS = 20_000


def plot_3d_voxel(
    a: hist.Hist, b: hist.Hist, label_a: str, label_b: str, comparison: str = "ratio"
):
    """
    Returns a list of (suffix, figure) pairs, like plot_2d.
    """
    va = a.values()
    vb = b.values()

    nfilled = numpy.count_nonzero(va) + numpy.count_nonzero(vb)
    if nfilled > MAX_VOXELS:
        warn(
            f"{sanitize_name(a.name)!r} has {nfilled} filled bins, "
            f"falling back to 3D scatter rendering"
        )
        return plot_3d_scatter(a, b, label_a, label_b, comparison)

    X, Y, Z = numpy.meshgrid(*(ax.edges for ax in a.axes), indexing="ij")
    vmax = max(va.max(), vb.max(), 1e-9)
    cmap = matplotlib.colormaps["viridis"]

    figs = []

    # sqrt scaling keeps low-content bins visible next to a dense core
    value_norm = matplotlib.colors.PowerNorm(0.5, vmin=0, vmax=vmax)
    for suffix, v, label in _value_panels(va, vb, label_a, label_b):
        fig, ax = _new_3d_panel(a, label)
        filled = v != 0
        scale = value_norm(numpy.abs(v))
        colors = cmap(scale)
        colors[..., 3] = numpy.clip(scale, 0.05, 0.6)
        ax.voxels(X, Y, Z, filled, facecolors=colors, edgecolors=None)
        fig.colorbar(
            matplotlib.cm.ScalarMappable(norm=value_norm, cmap=cmap),
            ax=ax,
            label=a.label or "entries",
            shrink=0.7,
            pad=0.1,
        )
        figs.append((suffix, fig))

    data = _comparison_values(a, b, comparison, label_a, label_b)
    filled = ~numpy.ma.getmaskarray(data.values)
    metric_cmap = matplotlib.colormaps["RdBu_r"]
    colors = metric_cmap(data.norm(data.values.filled(data.center)))
    colors[..., 3] = 0.5
    fig, ax = _new_3d_panel(a, data.label)
    ax.voxels(X, Y, Z, filled, facecolors=colors, edgecolors=None)
    fig.colorbar(
        matplotlib.cm.ScalarMappable(norm=data.norm, cmap=metric_cmap),
        ax=ax,
        label=data.label,
        shrink=0.7,
        pad=0.1,
    )
    figs.append((f"_{comparison}", fig))

    return figs


@dataclasses.dataclass(frozen=True)
class PlotSpec:
    """
    Picklable description of the plots for one comparison item, produced by
    ComparisonItem.plot_specs on the main process and consumed by
    render_plots, possibly in a worker process.
    """

    kind: str  # "1d", "2d", "3d" or "eff"
    h_a: Any
    h_b: Any
    err_a: Any = None  # only for "eff"
    err_b: Any = None  # only for "eff"
    renderer: Optional[str] = None  # only for "3d"
    comparison: str = "ratio"

    @property
    def raster(self) -> bool:
        # matplotlib does not reliably honor rasterized=True for 3D
        # collections, so 3D figures are embedded and saved as raster images
        return self.kind == "3d"


def svg_encode(svg):
    # Stackoverflow: https://stackoverflow.com/a/66718254/1928287
    # Ref: https://bl.ocks.org/jennyknuth/222825e315d45a738ed9d6e04c7a88d0
    # Encode an SVG string so it can be embedded into a data URL.
    def repl(m):
        c = m.group()
        return "'" if c == '"' else "%" + format(ord(c), "x")

    svg_enc = re.sub(r'["%#{}<>]', repl, str(svg))
    return " ".join(svg_enc.split())  # Compact whitespace


def plot_to_uri(figure, raster: bool = False):
    buf = io.BytesIO()

    if raster:
        # matplotlib does not reliably honor rasterized=True for 3D
        # collections, so embed such figures as PNG to keep the report small
        figure.savefig(buf, format="png", dpi=120)
        data = base64.b64encode(buf.getvalue()).decode("utf8")
        return f"data:image/png;base64,{data}"

    figure.savefig(buf, format="svg")

    #         datauri = f"data:image/svg+xml;base64,{base64.b64encode(buf.getvalue()).decode('utf8')}"

    data = buf.getvalue().decode("utf8")
    #  data = urllib.parse.quote(data)
    data = svg_encode(data)
    datauri = f"data:image/svg+xml;utf8,{data}"
    return datauri


def render_plots(specs, key, label_a, label_b, plot_dir, format: str):
    """
    Render the plot specs produced by ComparisonItem.plot_specs and return the
    data URIs for embedding in the report.

    This function only handles picklable inputs and does not need ROOT, so it
    can run in a worker process.
    """
    uris = []

    for spec in specs:
        if spec.kind == "eff":
            a, b = spec.h_a, spec.h_b

            lowest = 0
            largest = 1.015
            nonzero = numpy.concatenate(
                [a.values()[a.values() > 0], b.values()[b.values() > 0]]
            )
            if len(nonzero) > 0:
                lowest = numpy.min(nonzero)
                largest = numpy.max(nonzero)

            fig, (ax, rax) = plot_ratio_eff(
                a, spec.err_a, b, spec.err_b, label_a, label_b
            )
            ax.set_ylim(
                bottom=lowest * 0.99,
                top=largest * 1.008,
            )
            #  mplhep.atlas.text("Simulation Internal", ax=ax, loc=1)
            figures = [("", fig)]
        elif spec.kind == "2d":
            figures = plot_2d(spec.h_a, spec.h_b, label_a, label_b, spec.comparison)
        elif spec.kind == "3d":
            if spec.renderer == "scatter":
                figures = plot_3d_scatter(
                    spec.h_a, spec.h_b, label_a, label_b, spec.comparison
                )
            else:
                figures = plot_3d_voxel(
                    spec.h_a, spec.h_b, label_a, label_b, spec.comparison
                )
        elif spec.kind == "1d":
            fig, (ax, rax) = plot_1d(
                spec.h_a, spec.h_b, label_a, label_b, spec.comparison
            )
            #  mplhep.atlas.text("Simulation Internal", ax=ax, loc=1)
            figures = [("", fig)]
        else:
            raise ValueError(f"Unknown plot spec kind {spec.kind!r}")

        for fig_suffix, fig in figures:
            try:
                uris.append(plot_to_uri(fig, raster=spec.raster))
                if plot_dir is not None:
                    safe_key = key.replace("/", "_") + fig_suffix
                    if spec.raster:
                        # vector formats explode for 3D collections, save a
                        # raster image regardless of the requested format
                        fig.savefig(plot_dir / f"{safe_key}.png", dpi=120)
                    else:
                        fig.savefig(plot_dir / f"{safe_key}.{format}")
            except ValueError as e:
                rich.print(f"ERROR during plot: {e}")

            pyplot.close(fig)

    return uris
