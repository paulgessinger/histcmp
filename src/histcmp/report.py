from datetime import datetime
from pathlib import Path
import shutil
from typing import Union
import contextlib
from concurrent.futures import ProcessPoolExecutor, as_completed
import re
from emoji import emojize

import jinja2

from histcmp.compare import Comparison
from histcmp.checks import Status

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


def get_current_url():
    global current_url
    return current_url


#  def dateformat(d, fmt):
#  assert isinstance(d, datetime)
#  return d.strftime(fmt)


def make_environment() -> jinja2.Environment:
    env = jinja2.Environment(loader=jinja2.PackageLoader(package_name="histcmp"))

    env.globals["static_url"] = static_url

    env.globals["url_for"] = url_for
    env.globals["current_url"] = get_current_url
    env.globals["Status"] = Status

    env.filters["emojize"] = emojize
    #  env.filters["dateformat"] = dateformat

    return env


def copy_static(output: Path) -> None:
    static = Path(__file__).parent / "static"
    assert static.exists()
    dest = output / "static"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(static, dest)


def make_report(comparison: Comparison, output: Path):

    copy_static(output)

    env = make_environment()

    plot_dir = output / "plots"
    plot_dir.mkdir(exist_ok=True)

    for item in comparison.common:
        item.ensure_plots(plot_dir)
    #  for check in item.checks:
    #  check.ensure_plot(plot_dir)

    with (output / "index.html").open("w") as fh:
        fh.write(env.get_template("main.html.j2").render(comparison=comparison))
