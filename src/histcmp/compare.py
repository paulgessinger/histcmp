from pathlib import Path
from typing import Tuple, List, Any, Optional
import functools
from dataclasses import dataclass, field
import fnmatch

from rich.progress import track
from rich.text import Text
from rich.panel import Panel
from matplotlib import pyplot
import numpy

from histcmp.console import console, fail, info, good, warn
from histcmp.root_helpers import (
    integralAndError,
    get_bin_content,
    convert_hist,
    tefficiency_to_th1,
)
from histcmp.plot import plot_ratio, plot_ratio_eff, plot_to_uri
from histcmp import icons
import histcmp.checks
from histcmp.github import is_github_actions, github_actions_marker

from histcmp.checks import (
    CompatCheck,
    CompositeCheck,
    Status,
)
from histcmp.config import Config

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
        if any(c.status == Status.FAILURE and not c.is_disabled for c in self.checks):
            return Status.FAILURE
        if all(s == Status.SUCCESS for s in statuses):
            return Status.SUCCESS
        if any(s == Status.SUCCESS for s in statuses):
            return Status.SUCCESS

        return Status.INCONCLUSIVE
        #  raise RuntimeError("Shouldn't happen")

    def ensure_plots(self, report_dir: Path, plot_dir: Path):

        if isinstance(self.item_a, ROOT.TH2):
            h2_a = convert_hist(self.item_a)
            h2_b = convert_hist(self.item_b)

            for proj in [0, 1]:
                h1_a = h2_a.project(proj)
                h1_b = h2_b.project(proj)

                fig, _ = plot_ratio(h1_a, h1_b)
                #  fig.savefig(f"{self.key}_p{proj}.png")
                self._generic_plots.append(plot_to_uri(fig))

        elif isinstance(self.item_a, ROOT.TEfficiency):
            a, a_err = convert_hist(self.item_a)
            b, b_err = convert_hist(self.item_b)

            #  a = convert_hist(tefficiency_to_th1(self.item_a))
            #  b = convert_hist(tefficiency_to_th1(self.item_b))

            lowest = 0
            nonzero = numpy.concatenate(
                [a.values()[a.values() > 0], b.values()[b.values() > 0]]
            )
            if len(nonzero) > 0:
                lowest = numpy.min(nonzero)

            fig, (ax, rax) = plot_ratio_eff(a, a_err, b, b_err)
            #  fig, (ax, rax) = plot_ratio(a, b)
            ax.set_ylim(bottom=lowest * 0.9)

            self._generic_plots.append(plot_to_uri(fig))

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

    label_monitored: Optional[str] = None
    label_reference: Optional[str] = None

    items: list = field(default_factory=list)

    common: set = field(default_factory=set)
    a_only: set = field(default_factory=set)
    b_only: set = field(default_factory=set)

    title: str = "Histogram comparison"


def can_handle_item(item) -> bool:
    return isinstance(item, ROOT.TH1) or isinstance(
        item, ROOT.TEfficiency
    )  # and not isinstance(item, ROOT.TH2)


def compare(config: Config, a: Path, b: Path) -> Comparison:
    rf_a = ROOT.TFile.Open(str(a))
    rf_b = ROOT.TFile.Open(str(b))

    keys_a = {k.GetName() for k in rf_a.GetListOfKeys()}
    keys_b = {k.GetName() for k in rf_b.GetListOfKeys()}

    common = keys_a.intersection(keys_b)

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
            result.a_only.add(key)
            result.a_only.add(key)

        console.rule(f"{key} ({item_a.__class__.__name__})")

        if not can_handle_item(item_a):
            warn(f"Unable to handle item of type {type(item_a)}")
            continue

        item = ComparisonItem(key=key, item_a=item_a, item_b=item_b)

        configured_checks = {}
        for pattern, checks in config.checks.items():
            if not fnmatch.fnmatch(key, pattern):
                continue

            #  print(key, pattern, "matches")

            for cname, check_kw in checks.items():
                ctype = getattr(histcmp.checks, cname)
                if ctype not in configured_checks:
                    #  print("Adding", cname, "kw:", check_kw)
                    configured_checks[ctype] = (
                        {} if check_kw is None else check_kw.copy()
                    )
                else:
                    #  print("Modifying", cname)
                    if check_kw is None:
                        #  print("-> setting disabled")
                        configured_checks[ctype].update({"disabled": True})
                    else:
                        #  print("-> updating kw")
                        configured_checks[ctype].update(check_kw)

        #  print(configured_checks)

        for ctype, check_kw in configured_checks.items():
            #  print(ctype, check_kw)
            subchecks = []
            if isinstance(item_a, ROOT.TH2):
                for proj in "ProjectionX", "ProjectionY":
                    proj_a = getattr(item_a, proj)().Clone()
                    proj_b = getattr(item_b, proj)().Clone()
                    proj_a.SetDirectory(0)
                    proj_b.SetDirectory(0)
                    subchecks.append(
                        ctype(proj_a, proj_b, suffix="p" + proj[-1], **check_kw)
                    )
            else:
                subchecks.append(ctype(item_a, item_b, **check_kw))

            dstyle = "strike"
            for inst in subchecks:
                item.checks.append(inst)
                if inst.is_applicable:
                    if inst.is_valid:
                        console.print(
                            icons.success,
                            Text(
                                str(inst),
                                style="bold green" if not inst.is_disabled else dstyle,
                            ),
                            inst.label,
                        )
                    else:
                        if is_github_actions and not inst.is_disabled:
                            print(
                                github_actions_marker(
                                    "error",
                                    key + ": " + str(inst) + "\n" + inst.label,
                                )
                            )
                        console.print(
                            icons.failure,
                            Text(
                                str(inst),
                                style="bold red" if not inst.is_disabled else dstyle,
                            ),
                            inst.label,
                        )
                else:
                    console.print(icons.inconclusive, inst, style="yellow")

        result.items.append(item)

        if all(c.status == Status.INCONCLUSIVE for c in item.checks):
            print(github_actions_marker("warning", key + ": has no applicable checks"))

    result.b_only = {(k, rf_b.Get(k).__class__.__name__) for k in (keys_b - keys_a)}
    result.a_only = {(k, rf_a.Get(k).__class__.__name__) for k in (keys_a - keys_b)}
    result.common = {(k, rf_a.Get(k).__class__.__name__) for k in common}

    return result
