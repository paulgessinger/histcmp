import warnings
import io
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

import numpy

# Force a non-interactive backend before pyplot is imported. On macOS the
# default is the Cocoa backend, which spends ~30% of total runtime spinning up
# an NSWindow we never display. The SVG backend used by savefig() is selected
# per-call regardless of this setting.
import matplotlib
matplotlib.use("Agg")

import mplhep

import hist
from matplotlib import pyplot

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


def plot_ratio_eff(a, a_err, b, b_err, label_a, label_b):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig, (ax, rax) = pyplot.subplots(
            2, 1, gridspec_kw=dict(height_ratios=[2, 0.5], hspace=0.05)
        )

        a_err = numpy.maximum(0, a_err)
        b_err = numpy.maximum(0, b_err)

        a_vals = a.values()
        b_vals = b.values()

        mplhep.histplot(a_vals, a.axes[0].edges, yerr=a_err, ax=ax, label=label_a)
        mplhep.histplot(b_vals, b.axes[0].edges, yerr=b_err, ax=ax, label=label_b)

        ratio = a_vals / b_vals

        a_err = 0.5 * (a_err[0] + a_err[1])
        b_err = 0.5 * (b_err[0] + b_err[1])

        r_err = numpy.sqrt(
            (a_err / b_vals) ** 2 + (a_vals / b_vals ** 2 * b_err) ** 2
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

    ax.set_ylabel(a.label)

    ax.set_xlabel("")
    rax.set_xlabel(a.axes[0].name)
    rax.set_ylabel(f"{label_a} / {label_b}")
    ax.set_xticklabels([])

    rax.set_xlim(*ax.get_xlim())

    ax.set_title(a.name)
    ax.set_title(a.name)
    ax.legend()
    fig.align_ylabels()

    ax.set_ylim(top=1.015)
    #  fig.tight_layout()
    fig.subplots_adjust(left=0.14, right=0.95, top=0.9, bottom=0.1)

    return fig, (ax, rax)


def sanitize_name(s):
    return s.replace(r"\GT", r">").replace(r"\LT", "<")


def plot_ratio(a: hist.Hist, b: hist.Hist, label_a: str, label_b: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        fig, (ax, rax) = pyplot.subplots(
            2, 1, gridspec_kw=dict(height_ratios=[2, 0.5], hspace=0.05)
        )

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

    ax.set_ylabel(a.label)

    ax.set_xlabel("")
    ax.set_xticklabels([])

    rax.set_xlim(*ax.get_xlim())

    ax.set_title(sanitize_name(a.name))
    fig.align_ylabels()
    #  fig.tight_layout()
    fig.subplots_adjust(left=0.14, right=0.95, top=0.9, bottom=0.1)

    return fig, (ax, rax)


_SVG_ENCODE_TABLE = str.maketrans(
    {
        '"': "'",
        "%": "%25",
        "#": "%23",
        "{": "%7b",
        "}": "%7d",
        "<": "%3c",
        ">": "%3e",
    }
)


def svg_encode(svg):
    # Stackoverflow: https://stackoverflow.com/a/66718254/1928287
    # Ref: https://bl.ocks.org/jennyknuth/222825e315d45a738ed9d6e04c7a88d0
    return " ".join(str(svg).translate(_SVG_ENCODE_TABLE).split())


def plot_to_uri(figure):
    buf = io.BytesIO()
    figure.savefig(buf, format="svg")

    #         datauri = f"data:image/svg+xml;base64,{base64.b64encode(buf.getvalue()).decode('utf8')}"

    data = buf.getvalue().decode("utf8")
    #  data = urllib.parse.quote(data)
    data = svg_encode(data)
    datauri = f"data:image/svg+xml;utf8,{data}"
    return datauri


# Picklable description of all plots to render for one ComparisonItem. Built in
# the main process (which holds the ROOT objects), then shipped to a worker.
@dataclass
class PlotJob:
    key: str
    # Each spec is either:
    #   ("ratio", hist_a, hist_b, suffix)         — plot_ratio over two hist.Hists
    #   ("eff",   a, a_err, b, b_err)             — plot_ratio_eff over TEfficiency-derived data
    specs: List[Tuple] = field(default_factory=list)


def render_plot_job(
    job: PlotJob,
    label_a: str,
    label_b: str,
    plot_dir: Optional[Union[str, Path]],
    format: str,
) -> Tuple[str, List[str]]:
    """Render every plot in `job` and return (key, list_of_svg_data_uris).

    Safe to call from a worker process: touches only matplotlib + numpy +
    hist, never ROOT. Closes each figure as it goes to keep memory flat.
    """
    plot_dir_path = Path(plot_dir) if plot_dir is not None else None
    uris: List[str] = []
    for spec in job.specs:
        kind = spec[0]
        suffix = ""
        fig = None
        try:
            if kind == "ratio":
                _, h_a, h_b, suffix = spec
                fig, _ = plot_ratio(h_a, h_b, label_a, label_b)
            elif kind == "eff":
                _, a, a_err, b, b_err = spec
                fig, (ax, _rax) = plot_ratio_eff(a, a_err, b, b_err, label_a, label_b)
                nonzero = numpy.concatenate(
                    [a.values()[a.values() > 0], b.values()[b.values() > 0]]
                )
                if len(nonzero) > 0:
                    ax.set_ylim(
                        bottom=float(numpy.min(nonzero)) * 0.99,
                        top=float(numpy.max(nonzero)) * 1.008,
                    )
                else:
                    ax.set_ylim(bottom=0.0, top=1.015 * 1.008)
            else:
                continue

            uris.append(plot_to_uri(fig))
            if plot_dir_path is not None:
                safe_key = job.key.replace("/", "_") + suffix
                fig.savefig(plot_dir_path / f"{safe_key}.{format}")
        except ValueError as e:
            print(f"ERROR during plot ({job.key}{suffix}): {e}")
        finally:
            if fig is not None:
                pyplot.close(fig)
    return job.key, uris
