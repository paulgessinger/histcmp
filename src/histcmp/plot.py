import warnings
import io
import urllib.parse

#  from abc import ABC, abstractmethod, abstractproperty
#  from pathlib import Path

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
            main_ax_artists, subplot_ax_artists = a.plot_ratio(
                b,
                ax_dict=dict(main_ax=ax, ratio_ax=rax),
                rp_ylabel=r"monitored / reference",
                rp_num_label="monitored",
                rp_denom_label="reference",
                rp_uncert_draw_type="line",  # line or bar
            )
            markers, _, _ = subplot_ax_artists.errorbar.lines
            markers.set_markersize(2)
        except ValueError:
            ax.clear()
            rax.clear()
            a.plot(ax=ax)
            b.plot(ax=ax)

    ax.set_ylabel(a.label)

    ax.set_xlabel("")
    ax.set_xticklabels([])

    rax.set_xlim(*ax.get_xlim())

    ax.set_title(a.name)
    fig.align_ylabels()
    #  fig.tight_layout()
    fig.subplots_adjust(left=0.12, right=0.95, top=0.9, bottom=0.1)

    return fig, (ax, rax)


def plot_to_uri(figure):
    buf = io.BytesIO()
    figure.savefig(buf, format="svg")

    #         datauri = f"data:image/svg+xml;base64,{base64.b64encode(buf.getvalue()).decode('utf8')}"

    data = buf.getvalue().decode("utf8")
    data = urllib.parse.quote(data)
    datauri = f"data:image/svg+xml;utf8,{data}"
    return datauri
