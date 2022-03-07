import warnings
import io
import urllib.parse

#  from abc import ABC, abstractmethod, abstractproperty
#  from pathlib import Path
import numpy

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


def plot_ratio(a: hist.Hist, b: hist.Hist):
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

            #  print(ymin, ymax)
            main_ax_artists, subplot_ax_artists = a.plot_ratio(
                b,
                ax_dict=dict(main_ax=ax, ratio_ax=rax),
                rp_ylabel=r"monitored / reference",
                rp_num_label="monitored",
                rp_denom_label="reference",
                rp_uncert_draw_type="line",  # line or bar
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

    ax.set_title(a.name)
    fig.align_ylabels()
    #  fig.tight_layout()
    fig.subplots_adjust(left=0.12, right=0.95, top=0.9, bottom=0.1)

    return fig, (ax, rax)


def svg_encode(svg):
    # Stackoverflow: https://stackoverflow.com/a/66718254/1928287
    # Ref: https://bl.ocks.org/jennyknuth/222825e315d45a738ed9d6e04c7a88d0
    # Encode an SVG string so it can be embedded into a data URL.
    enc_chars = '"%#{}<>'  # Encode these to %hex
    enc_chars_maybe = "&|[]^`;?:@="  # Add to enc_chars on exception
    svg_enc = ""
    # Translate character by character
    for c in str(svg):
        if c in enc_chars:
            if c == '"':
                svg_enc += "'"
            else:
                svg_enc += "%" + format(ord(c), "x")
        else:
            svg_enc += c
    return " ".join(svg_enc.split())  # Compact whitespace


def plot_to_uri(figure):
    buf = io.BytesIO()
    figure.savefig(buf, format="svg")

    #         datauri = f"data:image/svg+xml;base64,{base64.b64encode(buf.getvalue()).decode('utf8')}"

    data = buf.getvalue().decode("utf8")
    #  data = urllib.parse.quote(data)
    data = svg_encode(data)
    datauri = f"data:image/svg+xml;utf8,{data}"
    return datauri
