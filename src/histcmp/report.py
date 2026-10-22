from datetime import datetime
from pathlib import Path
import os
import math
import sys
import shutil
from typing import Union, Optional
import contextlib
import re
from urllib.parse import quote
from fnmatch import fnmatchcase
from rich.progress import track
from rich.emoji import Emoji

import jinja2

from histcmp.jsplot import JSPlot
from histcmp.compare import Comparison
from histcmp.checks import Status
from histcmp.config import ReportConfig
from histcmp.console import console
from histcmp.root_helpers import push_root_level
from histcmp import icons

current_depth = 0
current_url = "/"


@contextlib.contextmanager
def push_depth(n: int = 1):
    global current_depth
    current_depth += n
    yield
    current_depth -= n


@contextlib.contextmanager
def push_url(url: Path):
    global current_url
    prev = current_url
    current_url = url
    with push_depth(len(current_url.parts)):
        yield
    current_url = prev


def prefix_url(prefix: str):
    def wrapped(url: Union[str, Path]):
        if isinstance(url, str):
            url = Path(url)
        assert isinstance(url, Path)
        return url_for(prefix / url)

    return wrapped


# def static_url(url: Union[str, Path]) -> Path:
#     if isinstance(url, str):
#         url = Path(url)
#     assert isinstance(url, Path)
#     return url_for("/static" / url)


def url_for(url: Union[str, Path]) -> Path:
    if isinstance(url, str):
        url = Path(url)
    assert isinstance(url, Path)

    prefix = Path(".")
    for _ in range(current_depth):
        prefix = prefix / ".."

    # print(prefix / url)

    return prefix / url


def path_sanitize(path: str) -> str:
    return path.replace("/", "_")


# static_url = prefix_url("static")


def static_url(url: Union[str, Path]) -> Path:
    if isinstance(url, str):
        url = Path(url)
    assert isinstance(url, Path)
    return url_for("static" / url)


def static_content(url: str) -> str:
    static = Path(__file__).parent / "static"
    candidate = static / url

    if not candidate.exists():
        raise ValueError(f"File at {candidate} not found")

    return candidate.read_text()


def get_current_url():
    global current_url
    return current_url


#  def dateformat(d, fmt):
#  assert isinstance(d, datetime)
#  return d.strftime(fmt)


def _emojize(s):
    return Emoji.replace(s)


def make_environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.PackageLoader(package_name="histcmp"),
        extensions=["jinja2.ext.loopcontrols"],
    )

    env.globals["static_url"] = static_url
    env.globals["static_content"] = static_content

    env.globals["icons"] = icons

    env.globals["url_for"] = url_for
    env.globals["current_url"] = get_current_url
    env.globals["Status"] = Status

    env.filters["emojize"] = _emojize

    #  env.filters["dateformat"] = dateformat

    return env


def copy_static(output: Path) -> None:
    static = Path(__file__).parent / "static"
    assert static.exists()
    dest = output / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(static, dest)


def report_plot_directory(output: Path, plot_dir: Optional[Path] = None) -> Path:
    if plot_dir is None:
        plot_dir = output.with_name(f"{output.stem}_plots")
    return plot_dir.resolve()


def check_metadata(check):
    value = check.sort_value if check.is_applicable and not check.is_disabled else None
    if value is not None:
        value = float(value)
        if math.isnan(value):
            value = None
        elif math.isinf(value):
            value = math.copysign(sys.float_info.max, value)
    return {
        "name": str(check), "status": check.status.name.lower(),
        "disabled": bool(check.is_disabled),
        "label": check.label if check.is_applicable else "Not applicable",
        "sortValue": value,
    }


def make_report(
    comparison: Comparison,
    output: Path,
    plot_dir: Optional[Path] = None,
    report_config: Optional[ReportConfig] = None,
):
    output.parent.mkdir(exist_ok=True, parents=True)
    plot_dir = report_plot_directory(output, plot_dir)
    plot_dir.mkdir(exist_ok=True, parents=True)

    #  copy_static(output)

    env = make_environment()
    report_config = report_config or ReportConfig()
    index = [
        {
            "id": f"plot-{i}",
            "title": item.key,
            "status": item.status.name.lower(),
            "checks": [check_metadata(check) for check in item.checks],
            "tags": [
                name for name, patterns in report_config.tags.items()
                if any(fnmatchcase(item.key, pattern) for pattern in patterns)
            ],
        }
        for i, item in enumerate(comparison.items)
    ]

    import ROOT

    with push_root_level(ROOT.kWarning):
        for item in track(
            comparison.items, description="Making plots", console=console
        ):
            item.ensure_plots(
                plot_dir,
                comparison.label_monitored,
                comparison.label_reference,
            )

    def plot_url(path: Path) -> str:
        relative = Path(os.path.relpath(path.resolve(), output.parent.resolve()))
        return quote(relative.as_posix())

    with output.open("w") as fh:
        fh.write(
            env.get_template("main.html.j2").render(
                comparison=comparison,
                is_js_plot=lambda plot: isinstance(plot, JSPlot),
                has_js_plots=any(isinstance(plot, JSPlot) for item in comparison.items for plot in item.generic_plots),
                plot_url=plot_url,
                report_index=index,
                tags=list(report_config.tags),
                totals={status.name.lower(): sum(item.status == status for item in comparison.items)
                        for status in Status},
                added=sorted(comparison.a_only),
                missing=sorted(comparison.b_only),
            )
        )
