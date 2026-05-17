from datetime import datetime
from pathlib import Path
import shutil
from typing import Union, Optional
import contextlib
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import re
from rich.progress import track
from rich.emoji import Emoji

import jinja2

from histcmp.compare import Comparison
from histcmp.checks import Status
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


def make_report(
    comparison: Comparison,
    output: Path,
    plot_dir: Optional[Path] = None,
    format: str = "pdf",
    n_workers: Optional[int] = None,
):

    #  copy_static(output)

    env = make_environment()

    import ROOT
    import os
    from histcmp.plot import render_plot_job

    # Build picklable plot payloads in the main process — convert_hist touches
    # ROOT objects that can't cross a process boundary.
    with push_root_level(ROOT.kWarning):
        jobs = [(item, item.build_plot_job()) for item in comparison.items]

    plot_dir_arg = str(plot_dir) if plot_dir is not None else None

    # Pool plumbing exists for very large reports, but for typical inputs the
    # forkserver + per-worker matplotlib import (~0.5s each) costs more than
    # the parallel render saves. Default to serial unless we have enough jobs
    # to amortize the startup, or the user passed -j explicitly.
    POOL_THRESHOLD = 100
    if n_workers is None:
        n_workers = min(os.cpu_count() or 1, 4) if len(jobs) >= POOL_THRESHOLD else 1
    n_workers = max(1, min(n_workers, len(jobs)))

    if n_workers <= 1 or len(jobs) <= 1:
        # Serial path (also the default for typical input sizes).
        for item, job in track(
            jobs, description="Making plots", console=console
        ):
            _, uris = render_plot_job(
                job,
                comparison.label_monitored,
                comparison.label_reference,
                plot_dir_arg,
                format,
            )
            item.set_plot_uris(uris)
    else:
        # Prefer 'forkserver' over the default 'spawn' on macOS/Linux: a small
        # parent process pre-imports histcmp.plot (and therefore matplotlib +
        # mplhep + hist), then each worker is forked from that hot template
        # instead of cold-starting a Python interpreter. Cuts ~0.5s/worker of
        # import overhead, which matters because we only have ~30 jobs to
        # amortize the pool over. Fall back to default if forkserver isn't
        # available (Windows).
        try:
            mp_context = multiprocessing.get_context("forkserver")
        except (ValueError, AttributeError):
            mp_context = None

        items_by_key = {item.key: item for item, _ in jobs}
        with ProcessPoolExecutor(max_workers=n_workers, mp_context=mp_context) as pool:
            futures = [
                pool.submit(
                    render_plot_job,
                    job,
                    comparison.label_monitored,
                    comparison.label_reference,
                    plot_dir_arg,
                    format,
                )
                for _, job in jobs
            ]
            for fut in track(
                as_completed(futures),
                total=len(futures),
                description="Making plots",
                console=console,
            ):
                key, uris = fut.result()
                items_by_key[key].set_plot_uris(uris)

    with output.open("w") as fh:
        fh.write(env.get_template("main.html.j2").render(comparison=comparison))
