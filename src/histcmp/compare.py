from pathlib import Path
from typing import Tuple, List, Any, Optional
import functools
from dataclasses import dataclass, field
import fnmatch
import re

import rich
from rich.progress import track
from rich.text import Text
from rich.panel import Panel
from matplotlib import pyplot
import numpy
import mplhep.atlas

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

    def ensure_plots(
        self,
        report_dir: Path,
        plot_dir: Path,
        label_a: str,
        label_b: str,
        format: str,
    ):
        figs = []

        if isinstance(self.item_a, ROOT.TH2):
            h2_a = convert_hist(self.item_a)
            h2_b = convert_hist(self.item_b)

            for proj in [0, 1]:
                h1_a = h2_a.project(proj)
                h1_b = h2_b.project(proj)

                fig, (ax, rax) = plot_ratio(h1_a, h1_b, label_a, label_b)

                d = "XY"[proj]

                figs.append((fig, f"_p{d}"))
                #  mplhep.atlas.text("Simulation Internal", ax=ax, loc=1)

        elif isinstance(self.item_a, ROOT.TEfficiency):
            a, a_err = convert_hist(self.item_a)
            b, b_err = convert_hist(self.item_b)

            lowest = 0
            largest = 1.015
            nonzero = numpy.concatenate(
                [a.values()[a.values() > 0], b.values()[b.values() > 0]]
            )
            if len(nonzero) > 0:
                lowest = numpy.min(nonzero)
                largest = numpy.max(nonzero)

            fig, (ax, rax) = plot_ratio_eff(a, a_err, b, b_err, label_a, label_b)
            figs.append((fig, ""))
            ax.set_ylim(
                bottom=lowest * 0.99,
                top=largest * 1.008,
            )
            #  mplhep.atlas.text("Simulation Internal", ax=ax, loc=1)

        elif isinstance(self.item_a, ROOT.TH1):
            a = convert_hist(self.item_a)
            b = convert_hist(self.item_b)
            fig, (ax, rax) = plot_ratio(a, b, label_a, label_b)
            figs.append((fig, ""))

            #  mplhep.atlas.text("Simulation Internal", ax=ax, loc=1)

        for fig, suffix in figs:
            try:
                self._generic_plots.append(plot_to_uri(fig))
                if plot_dir is not None:
                    safe_key = self.key.replace("/", "_") + suffix
                    fig.savefig(plot_dir / f"{safe_key}.{format}")
            except ValueError as e:
                rich.print(f"ERROR during plot: {e}")

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
    if isinstance(item, ROOT.TH1):
        return True
    if isinstance(item, ROOT.TEfficiency):
        return item.GetDimension() == 1
    return False


def collect_items(d, prefix=None):
    items = {}
    dname = d.GetName()
    if isinstance(d, ROOT.TFile):
        dname = ""
    for k in d.GetListOfKeys():
        obj = k.ReadObj()
        #  print(type(obj))
        if isinstance(obj, ROOT.TDirectoryFile):
            items.update(
                collect_items(
                    obj,
                    prefix + dname + k.GetName() + "__" if prefix is not None else "",
                )
            )
            continue
        if (
            not isinstance(obj, ROOT.TH1)
            and not isinstance(obj, ROOT.TH2)
            and not isinstance(obj, ROOT.TEfficiency)
        ):
            continue
        obj.SetDirectory(0)
        p = prefix or ""
        #  print(prefix)
        ik = (
            p + dname + "__" + k.GetName() if (dname != "" and p != "") else k.GetName()
        )
        items[ik] = obj
    return items


def compare(config: Config, a: Path, b: Path, filters: List[str]) -> Comparison:
    rf_a = ROOT.TFile.Open(str(a))
    rf_b = ROOT.TFile.Open(str(b))

    key_map_a = collect_items(rf_a)
    key_map_b = collect_items(rf_b)

    keys_a = set(key_map_a.keys())
    keys_b = set(key_map_b.keys())
    #  keys_a = {k.GetName() for k in rf_a.GetListOfKeys()}
    #  keys_b = {k.GetName() for k in rf_b.GetListOfKeys()}

    #  key_map_a = {k.GetName(): k for k in rf_a.GetListOfKeys()}
    #  key_map_b = {k.GetName(): k for k in rf_b.GetListOfKeys()}
    common = keys_a.intersection(keys_b)

    #  print(common)
    def select(s) -> bool:
        accepted = True
        rejected = False
        for f in filters:
            if f.startswith("! "):
                if re.match(f[2:], s):
                    rejected = True
            else:
                if not re.match(f, s):
                    accepted = False
        return accepted and not rejected

    common = set(filter(select, common))

    #  print(common)

    #  import sys

    #  sys.exit()

    result = Comparison(file_a=str(a), file_b=str(b))

    for key in track(sorted(common), console=console, description="Comparing..."):
        item_a = key_map_a[key]
        item_b = key_map_b[key]

        #  item_a.SetDirectory(0)
        #  item_b.SetDirectory(0)

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
                    if check_kw is not None:
                        configured_checks[ctype] = check_kw.copy()
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
