from pathlib import Path
from typing import Tuple, List, Any, Optional
import functools
from dataclasses import dataclass, field
import fnmatch
import re

from rich.progress import track
from rich.text import Text

from histcmp.console import console, fail, warn
from histcmp.root_helpers import (
    integralAndError,
    get_bin_content,
    convert_hist,
    tefficiency_to_th1,
)
from histcmp.plot import PlotJob, render_plot_job
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

    def build_plot_job(self) -> PlotJob:
        """Extract every histogram needed for plotting into a picklable PlotJob.

        Runs in the main process (it touches ROOT objects). The returned job
        can be shipped to a worker for parallel matplotlib rendering.
        """
        job = PlotJob(key=self.key)

        if isinstance(self.item_a, ROOT.TH3):
            h_a = convert_hist(self.item_a)
            h_b = convert_hist(self.item_b)
            for proj, d in enumerate("XYZ"):
                job.specs.append(("ratio", h_a.project(proj), h_b.project(proj), f"_p{d}"))
        elif isinstance(self.item_a, ROOT.TH2):
            h_a = convert_hist(self.item_a)
            h_b = convert_hist(self.item_b)
            for proj, d in enumerate("XY"):
                job.specs.append(("ratio", h_a.project(proj), h_b.project(proj), f"_p{d}"))
        elif isinstance(self.item_a, ROOT.TEfficiency):
            a, a_err = convert_hist(self.item_a)
            b, b_err = convert_hist(self.item_b)
            job.specs.append(("eff", a, a_err, b, b_err))
        elif isinstance(self.item_a, ROOT.TH1):
            job.specs.append(
                ("ratio", convert_hist(self.item_a), convert_hist(self.item_b), "")
            )

        return job

    def set_plot_uris(self, uris):
        self._generic_plots = list(uris)

    def ensure_plots(
        self,
        report_dir: Path,
        plot_dir: Path,
        label_a: str,
        label_b: str,
        format: str,
    ):
        """Sequential fallback / single-item entry point. The parallel path in
        make_report goes through build_plot_job + render_plot_job directly.
        """
        job = self.build_plot_job()
        _, uris = render_plot_job(job, label_a, label_b, plot_dir, format)
        self.set_plot_uris(uris)

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
        # Resolve the class from the key without deserializing the payload.
        # ReadObj is expensive (decompress + stream), so skip it for objects
        # we'd just discard (TGraph, TCanvas, TTree, ...).
        cls = ROOT.TClass.GetClass(k.GetClassName())
        if cls is None:
            continue
        if cls.InheritsFrom("TDirectoryFile"):
            obj = k.ReadObj()
            items.update(
                collect_items(
                    obj,
                    prefix + dname + k.GetName() + "__" if prefix is not None else "",
                )
            )
            continue
        if not (cls.InheritsFrom("TH1") or cls.InheritsFrom("TEfficiency")):
            continue
        obj = k.ReadObj()
        obj.SetDirectory(0)
        p = prefix or ""
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

        # Project TH2/TH3 once per item rather than once per check type — the
        # ROOT Projection* calls are O(Nbins) and were previously repeated for
        # every configured check.
        projections = []
        if isinstance(item_a, ROOT.TH3):
            proj_names = ("ProjectionX", "ProjectionY", "ProjectionZ")
        elif isinstance(item_a, ROOT.TH2):
            proj_names = ("ProjectionX", "ProjectionY")
        else:
            proj_names = ()
        for proj in proj_names:
            proj_a = getattr(item_a, proj)().Clone()
            proj_b = getattr(item_b, proj)().Clone()
            proj_a.SetDirectory(0)
            proj_b.SetDirectory(0)
            projections.append((proj_a, proj_b, "p" + proj[-1]))

        for ctype, check_kw in configured_checks.items():
            subchecks = []
            for proj_a, proj_b, sfx in projections:
                subchecks.append(ctype(proj_a, proj_b, suffix=sfx, **check_kw))
            # Preserve original behaviour: TH3 also gets a full-volume check,
            # TH2 only gets projections, TH1 only gets the full-hist check.
            if not isinstance(item_a, ROOT.TH2):
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
