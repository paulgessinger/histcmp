"""
Worker process side of the parallel comparison: each worker opens the two
ROOT files once, then processes items scheduled by name — reading the
objects, running the configured checks and rendering the plots. ROOT objects
cannot be pickled, so only key strings and paths go in; the returned checks
turn into their picklable CheckSummary on the way back (CompatCheck.__reduce__).
The per-run constants (config, labels, plot directory, format) are shipped
once via the pool initializer instead of with every item.
"""

from pathlib import Path
from typing import Optional

_rf_a = None
_rf_b = None
_config = None
_label_a = None
_label_b = None
_plot_dir = None
_format = None


def init_worker(
    file_a: str,
    file_b: str,
    config,
    label_a: str,
    label_b: str,
    plot_dir: Optional[Path],
    format: str,
):
    import matplotlib

    matplotlib.use("Agg", force=True)

    import ROOT

    ROOT.gROOT.SetBatch(True)
    ROOT.gErrorIgnoreLevel = ROOT.kWarning

    global _rf_a, _rf_b, _config, _label_a, _label_b, _plot_dir, _format
    _rf_a = ROOT.TFile.Open(file_a)
    _rf_b = ROOT.TFile.Open(file_b)
    _config = config
    _label_a = label_a
    _label_b = label_b
    _plot_dir = plot_dir
    _format = format


def _read(rf, path: str):
    obj = rf.Get(path)
    if hasattr(obj, "SetDirectory"):
        obj.SetDirectory(0)
    return obj


def process_item(key: str, path_a: str, path_b: str):
    from histcmp.compare import build_checks, build_plot_specs, can_handle_item
    from histcmp.plot import render_plots

    item_a = _read(_rf_a, path_a)
    item_b = _read(_rf_b, path_b)

    if not can_handle_item(item_a):
        return None

    checks = build_checks(_config.checks, key, item_a, item_b)
    plots = render_plots(
        build_plot_specs(item_a, item_b, _config.plots),
        key,
        _label_a,
        _label_b,
        _plot_dir,
        _format,
    )

    return checks, plots
