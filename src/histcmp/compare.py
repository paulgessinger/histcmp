from pathlib import Path
from typing import Tuple, List, Any
import functools
from dataclasses import dataclass, field

from rich.progress import track
from matplotlib import pyplot
import numpy

from histcmp.console import console, fail, info, good, warn
from histcmp.root_helpers import integralAndError, get_bin_content, convert_hist
from histcmp.plot import plot_ratio, plot_to_uri
from histcmp import icons
from histcmp.checks import (
    CompatCheck,
    Chi2Test,
    KolmogorovTest,
    IntegralCheck,
    RatioCheck,
    ResidualCheck,
    Status,
)

import ROOT


class ComparisonItem:
    key: str
    item_a: Any
    item_b: Any
    checks: List[CompatCheck]

    def __init__(self, key: str, item_a, item_b):
        self.key = key
        self.item_a = item_a
        self.item_b = item_b
        self._generic_plots = []
        self.checks = []

    @functools.cached_property
    def status(self) -> Status:
        statuses = [c.status for c in self.checks]
        if any(s == Status.FAILURE for s in statuses):
            return Status.FAILURE
        if all(s == Status.SUCCESS for s in statuses):
            return Status.SUCCESS
        if any(s == Status.SUCCESS for s in statuses):
            return Status.SUCCESS

        return Status.INCONCLUSIVE
        #  raise RuntimeError("Shouldn't happen")

    def ensure_plots(self, report_dir: Path, plot_dir: Path):
        #  for check in self.checks:
        #  check.ensure_plot(self.key, report_dir, plot_dir)

        #  print("MAKE PLOT")
        #  print(type(self.item_a))
        #  print(isinstance(self.item_a, ROOT.TH1), isinstance(self.item_a, ROOT.TH2))

        def do_plot(item_a, item_b, out):
            c = ROOT.TCanvas("c1")
            item_a.SetLineColor(ROOT.kBlue)
            item_a.Draw()
            item_b.SetLineColor(ROOT.kRed)
            item_b.Draw("same")

            if isinstance(item_a, ROOT.TEfficiency):
                ha = item_a.CreateGraph().GetHistogram()
                hb = item_b.CreateGraph().GetHistogram()
                maximum = max(ha.GetMaximum(), hb.GetMaximum())
                minimum = max(ha.GetMinimum(), hb.GetMinimum())
                ROOT.gPad.Update()
                graph = item_a.GetPaintedGraph()
                graph.SetMinimum(minimum)
                graph.SetMaximum(maximum)
            else:
                maximum = max(item_a.GetMaximum(), item_b.GetMaximum())
                minimum = max(item_a.GetMinimum(), item_b.GetMinimum())
                item_a.GetYaxis().SetRangeUser(
                    minimum, minimum + (maximum - minimum) * 1.2
                )

            legend = ROOT.TLegend(0.1, 0.8, 0.9, 0.9)
            legend.SetNColumns(2)
            #  legend.SetHeader("The Legend Title","C"
            legend.AddEntry(item_a, "reference")
            legend.AddEntry(item_b, "current")
            legend.Draw()
            c.SaveAs(out)

        if isinstance(self.item_a, ROOT.TH2):
            h2_a = convert_hist(self.item_a)
            h2_b = convert_hist(self.item_b)

            for proj in [0, 1]:
                h1_a = h2_a.project(proj)
                h1_b = h2_b.project(proj)

                fig, _ = plot_ratio(h1_a, h1_b)
                #  fig.savefig(f"{self.key}_p{proj}.png")
                self._generic_plots.append(plot_to_uri(fig))

            #  for proj in "ProjectionX", "ProjectionY":
            #  p = plot_dir / f"{self.key}_overlay_{proj}.png"
            #  if p.exists():
            #  continue
            #  item_a = getattr(self.item_a, proj)().Clone()
            #  item_b = getattr(self.item_b, proj)().Clone()
            #  item_a.SetDirectory(0)
            #  item_b.SetDirectory(0)
            #  do_plot(
            #  item_a,
            #  item_b,
            #  str(report_dir / p),
            #  )
            #  self._generic_plots.append(p)
        elif isinstance(self.item_a, ROOT.TEfficiency):
            a = convert_hist(self.item_a)
            b = convert_hist(self.item_b)

            # find lowest non-zero entry
            #  print(a.values()[a.values() > 0])
            #  print(b.values()[b.values() > 0])
            lowest = 0
            nonzero = numpy.concatenate(
                [a.values()[a.values() > 0], b.values()[b.values() > 0]]
            )
            if len(nonzero) > 0:
                lowest = numpy.min(nonzero)
            #  print(lowest)

            fig, (ax, rax) = plot_ratio(a, b)
            ax.set_ylim(bottom=lowest * 0.9)

            #  fig.savefig(f"{self.key}.png")
            self._generic_plots.append(plot_to_uri(fig))

            #  p = plot_dir / f"{self.key}_overlay.png"
            #  if not (report_dir / p).exists():
            #  do_plot(self.item_a, self.item_b, str(report_dir / p))

            #  self._generic_plots.append(p)

        elif isinstance(self.item_a, ROOT.TH1):
            a = convert_hist(self.item_a)
            b = convert_hist(self.item_b)
            fig, _ = plot_ratio(a, b)
            #  fig.savefig(f"{self.key}.png")
            self._generic_plots.append(plot_to_uri(fig))

    @property
    def first_plot_index(self):
        for i, v in enumerate(self.checks):
            if v.plot is not None:
                return i

    @property
    def generic_plots(self) -> List[Path]:
        return self._generic_plots


@dataclass
class Comparison:
    file_a: str
    file_b: str
    common: list = field(default_factory=list)


def can_handle_item(item) -> bool:
    return isinstance(item, ROOT.TH1) or isinstance(
        item, ROOT.TEfficiency
    )  # and not isinstance(item, ROOT.TH2)


def compare(a: Path, b: Path) -> Comparison:
    rf_a = ROOT.TFile.Open(str(a))
    rf_b = ROOT.TFile.Open(str(b))

    keys_a = {k.GetName() for k in rf_a.GetListOfKeys()}
    keys_b = {k.GetName() for k in rf_b.GetListOfKeys()}

    common = keys_a.intersection(keys_b)

    removed = keys_b - keys_a
    new = keys_a - keys_b

    console.print(
        f":information: {len(common)} common elements between files", style="info"
    )

    result = Comparison(file_a=str(a), file_b=str(b))

    for key in track(sorted(common), console=console, description="Comparing..."):

        item_a = rf_a.Get(key)
        item_b = rf_b.Get(key)

        item_a.SetDirectory(0)
        item_b.SetDirectory(0)

        if type(item_a) != type(item_b):
            console.rule(f"{key}")
            fail(
                f"Type mismatch between files for key {key}: {item_a} != {type(item_b)} => treating as both removed and newly added"
            )
            removed.add(key)
            new.add(key)

        console.rule(f"{key} ({item_a.__class__.__name__})")

        if not can_handle_item(item_a):
            warn(f"Unable to handle item of type {type(item_a)}")
            continue

        item = ComparisonItem(key=key, item_a=item_a, item_b=item_b)

        for test in (
            KolmogorovTest,
            RatioCheck,
            Chi2Test,
            ResidualCheck,
            IntegralCheck,
        ):
            inst = test(item_a, item_b)
            item.checks.append(inst)
            if inst.is_applicable:
                if inst.is_valid:
                    console.print(icons.success, inst, inst.label, style="bold green")
                else:
                    console.print(icons.failure, inst, inst.label, style="bold red")
            else:
                console.print(icons.inconclusive, inst, style="yellow")
        result.common.append(item)

    info(f"{len(removed)} elements are missing in new file")
    info(f"{len(new)} elements are added new file")

    return result
