from pathlib import Path
from typing import Tuple, List, Any, Optional
import functools
from dataclasses import dataclass, field
import fnmatch
import re

from rich.progress import track
from rich.text import Text
from rich.panel import Panel

from histcmp.console import console, fail, info, good, warn
from histcmp.root_helpers import convert_hist
from histcmp.plot import render_plots, PlotSpec
from histcmp import icons
import histcmp.checks
from histcmp.github import is_github_actions, github_actions_marker

from histcmp.checks import (
    CompatCheck,
    CompositeCheck,
    Status,
)
from histcmp.config import Config, PlotConfig

import ROOT


class ComparisonItem:
    key: str
    item_a: Any
    item_b: Any
    checks: List[CompatCheck]

    def __init__(
        self,
        key: str,
        item_a,
        item_b,
        plots: Optional[PlotConfig] = None,
    ):
        self.key = key
        self.item_a = item_a
        self.item_b = item_b
        self.plots = plots if plots is not None else PlotConfig()
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

    def plot_specs(self):
        return build_plot_specs(self.item_a, self.item_b, self.plots)

    def ensure_plots(
        self,
        report_dir: Path,
        plot_dir: Path,
        label_a: str,
        label_b: str,
        format: str,
    ):
        if self._generic_plots:
            # already rendered, e.g. by a worker process during compare()
            return
        self._generic_plots = render_plots(
            self.plot_specs(), self.key, label_a, label_b, plot_dir, format
        )

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


def build_plot_specs(item_a, item_b, plots: PlotConfig):
    """
    Build the picklable plot specifications for an item. This converts the
    ROOT objects into plain numpy backed histograms, so the result can be
    shipped across process boundaries and rendered with
    histcmp.plot.render_plots.
    """
    specs = []

    if isinstance(item_a, ROOT.TH3):
        specs.append(
            PlotSpec(
                "3d",
                convert_hist(item_a),
                convert_hist(item_b),
                renderer=plots.renderer_3d,
                comparison=plots.effective_comparison_2d3d,
            )
        )

    elif isinstance(item_a, ROOT.TH2):
        specs.append(
            PlotSpec(
                "2d",
                convert_hist(item_a),
                convert_hist(item_b),
                comparison=plots.effective_comparison_2d3d,
            )
        )

    elif isinstance(item_a, ROOT.TEfficiency):
        a, a_err = convert_hist(item_a)
        b, b_err = convert_hist(item_b)

        specs.append(PlotSpec("eff", a, b, err_a=a_err, err_b=b_err))

    elif isinstance(item_a, ROOT.TH1):
        specs.append(
            PlotSpec(
                "1d",
                convert_hist(item_a),
                convert_hist(item_b),
                comparison=plots.comparison,
            )
        )

    return specs


def collect_items(d, prefix=None, lazy=False, dirpath=""):
    """
    Collect the histogram-like objects of a file, keyed by flattened name.

    With lazy=True nothing but directories is read from the file: the values
    are (classname, path-within-file) tuples instead of the objects, so
    worker processes can read the objects themselves via TFile.Get(path).
    """
    items = {}
    dname = d.GetName()
    if isinstance(d, ROOT.TFile):
        dname = ""
    for k in d.GetListOfKeys():
        tclass = ROOT.TClass.GetClass(k.GetClassName())
        if tclass is None:
            continue
        if tclass.InheritsFrom("TDirectoryFile"):
            items.update(
                collect_items(
                    k.ReadObj(),
                    prefix + dname + k.GetName() + "__" if prefix is not None else "",
                    lazy=lazy,
                    dirpath=dirpath + k.GetName() + "/",
                )
            )
            continue
        if not tclass.InheritsFrom("TH1") and not tclass.InheritsFrom("TEfficiency"):
            continue
        p = prefix or ""
        #  print(prefix)
        ik = (
            p + dname + "__" + k.GetName() if (dname != "" and p != "") else k.GetName()
        )
        if lazy:
            items[ik] = (k.GetClassName(), dirpath + k.GetName())
        else:
            obj = k.ReadObj()
            obj.SetDirectory(0)
            items[ik] = obj
    return items


def build_checks(config_checks: dict, key: str, item_a, item_b) -> List[CompatCheck]:
    configured_checks = {}
    for pattern, checks in config_checks.items():
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

    return [
        ctype(item_a, item_b, **check_kw)
        for ctype, check_kw in configured_checks.items()
    ]


def report_item_console(key: str, checks):
    dstyle = "strike"
    for inst in checks:
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

    if all(c.status == Status.INCONCLUSIVE for c in checks):
        print(github_actions_marker("warning", key + ": has no applicable checks"))


def compare(
    config: Config,
    a: Path,
    b: Path,
    filters: List[str],
    enable_2d: bool = True,
    enable_3d: bool = True,
    jobs: int = 1,
    label_monitored: Optional[str] = None,
    label_reference: Optional[str] = None,
    plot_dir: Optional[Path] = None,
    format: str = "pdf",
) -> Comparison:
    rf_a = ROOT.TFile.Open(str(a))
    rf_b = ROOT.TFile.Open(str(b))

    key_map_a = collect_items(rf_a, lazy=jobs > 1)
    key_map_b = collect_items(rf_b, lazy=jobs > 1)

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

    if jobs > 1:
        _compare_parallel(
            result,
            config,
            common,
            key_map_a,
            key_map_b,
            enable_2d,
            enable_3d,
            jobs,
            label_monitored,
            label_reference,
            plot_dir,
            format,
        )
        result.b_only = {(k, key_map_b[k][0]) for k in (keys_b - keys_a)}
        result.a_only = {(k, key_map_a[k][0]) for k in (keys_a - keys_b)}
        result.common = {(k, key_map_a[k][0]) for k in common}

        return result

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

        # note: TH3 does not inherit from TH2, so the order doesn't matter
        if not enable_3d and isinstance(item_a, ROOT.TH3):
            info(f"Skipping 3D item {key}")
            continue
        if not enable_2d and isinstance(item_a, ROOT.TH2):
            info(f"Skipping 2D item {key}")
            continue

        if not can_handle_item(item_a):
            warn(f"Unable to handle item of type {type(item_a)}")
            continue

        item = ComparisonItem(
            key=key, item_a=item_a, item_b=item_b, plots=config.plots
        )
        item.checks = build_checks(config.checks, key, item_a, item_b)
        report_item_console(key, item.checks)

        result.items.append(item)

    result.b_only = {(k, rf_b.Get(k).__class__.__name__) for k in (keys_b - keys_a)}
    result.a_only = {(k, rf_a.Get(k).__class__.__name__) for k in (keys_a - keys_b)}
    result.common = {(k, rf_a.Get(k).__class__.__name__) for k in common}

    return result


def _compare_parallel(
    result: Comparison,
    config: Config,
    common: set,
    key_map_a: dict,
    key_map_b: dict,
    enable_2d: bool,
    enable_3d: bool,
    jobs: int,
    label_monitored: Optional[str],
    label_reference: Optional[str],
    plot_dir: Optional[Path],
    format: str,
):
    """
    Compare the common items by scheduling them by name onto worker processes
    which read the objects from the files themselves, run the checks and
    render the plots (see histcmp.worker). The main process only prints the
    results and assembles the comparison items from the returned summaries.
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from histcmp.worker import init_worker, process_item

    with ProcessPoolExecutor(
        max_workers=jobs,
        initializer=init_worker,
        initargs=(
            result.file_a,
            result.file_b,
            config,
            label_monitored,
            label_reference,
            plot_dir,
            format,
        ),
    ) as executor:
        futures = {}
        for key in sorted(common):
            cls_a, path_a = key_map_a[key]
            cls_b, path_b = key_map_b[key]

            if cls_a != cls_b:
                console.rule(f"{key}")
                fail(
                    f"Type mismatch between files for key {key}: {cls_a} != {cls_b} => treating as both removed and newly added"
                )
                result.a_only.add(key)

            tclass = ROOT.TClass.GetClass(cls_a)
            # note: TH3 does not inherit from TH2, so the order doesn't matter
            if not enable_3d and tclass.InheritsFrom("TH3"):
                console.rule(f"{key} ({cls_a})")
                info(f"Skipping 3D item {key}")
                continue
            if not enable_2d and tclass.InheritsFrom("TH2"):
                console.rule(f"{key} ({cls_a})")
                info(f"Skipping 2D item {key}")
                continue

            futures[executor.submit(process_item, key, path_a, path_b)] = key

        results = {}
        for future in track(
            as_completed(futures),
            total=len(futures),
            description="Comparing...",
            console=console,
        ):
            results[futures[future]] = future.result()

    for key in sorted(results):
        cls_a, _ = key_map_a[key]
        console.rule(f"{key} ({cls_a})")

        if results[key] is None:
            warn(f"Unable to handle item of type {cls_a}")
            continue

        checks, plots = results[key]

        item = ComparisonItem(key=key, item_a=None, item_b=None, plots=config.plots)
        item.checks = checks
        item._generic_plots = plots
        report_item_console(key, item.checks)

        result.items.append(item)
