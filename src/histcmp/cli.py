from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Union, IO
import sys

import typer
from rich.panel import Panel
from rich.console import Group
from rich.text import Text
from rich.rule import Rule
from rich.pretty import Pretty
from rich.emoji import Emoji
import jinja2
import yaml

from histcmp.console import Console
from histcmp.report import make_report
from histcmp.checks import Status
from histcmp.config import Config
from histcmp.github import is_github_actions, github_actions_marker

try:
    import ROOT
except ImportError:
    Console().fail("ROOT could not be imported")
    sys.exit(1)
ROOT.gROOT.SetBatch(ROOT.kTRUE)

from histcmp.compare import compare, Comparison


#  install(show_locals=True)

app = typer.Typer()


@contextmanager
def auto_console(file: str) -> IO[str]:
    if file == "-":
        yield Console()
    else:
        file = Path(file)
        with file.open("w") as fh:
            yield Console(file=fh)


def print_summary(comparison: Comparison, console: Console) -> Status:
    status = Status.SUCCESS
    style = "bold green"
    failures = [c for c in comparison.items if c.status == Status.FAILURE]
    inconclusive = [c for c in comparison.items if c.status == Status.INCONCLUSIVE]
    msg = [
        Text.from_markup(
            f"[cyan]{len(comparison.items)}[/cyan] checked items valid",
            justify="center",
        ),
    ]

    if len(failures) > 0 or len(comparison.a_only) > 0 or len(comparison.b_only) > 0:
        status = Status.FAILURE
        style = "bold red"
        msg = [
            Text.from_markup(
                f"[cyan]{len(failures)}[/cyan] items failed checks out of [cyan]{len(comparison.items)}[/cyan] common items",
                justify="center",
            ),
        ]
        if len(comparison.a_only) > 0:
            msg += [
                Rule(
                    style=style,
                    title=f"Monitored contains {len(comparison.a_only)} elements not in reference",
                ),
                Text(", ".join(f"{k} ({t})" for k, t in comparison.a_only)),
            ]
        if len(comparison.b_only) > 0:
            msg += [
                Rule(
                    style=style,
                    title=f"Reference contains {len(comparison.b_only)} elements not in monitored",
                ),
                Text(", ".join(f"{k} ({t})" for k, t in comparison.b_only)),
            ]

        if is_github_actions:
            print(
                github_actions_marker(
                    "error",
                    f"Comparison between {monitored} and {reference} failed!",
                )
            )
    elif len(inconclusive) > 0:
        status = Status.INCONCLUSIVE
        style = "bold yellow"
        msg = [
            Rule(style=style),
            Text(
                f"[cyan]{len(inconclusive)}[/cyan] items had inconclusive checks out of [cyan]{len(comparison.items)}[/cyan] common items"
            ),
        ]
        if is_github_actions:
            print(
                github_actions_marker(
                    "error",
                    f"Comparison between {monitored} and {reference} was inconclusive!",
                )
            )

    console.print(
        Panel(
            Group(
                Text(f"{Emoji.replace(status.icon)} {status.name}", justify="center"),
                *msg,
            ),
            style=style,
        )
    )

    return status


@app.command()
def main(
    config_path: Path = typer.Option(
        None, "--config", "-c", dir_okay=False, exists=True
    ),
    monitored: Path = typer.Argument(..., exists=True, dir_okay=False),
    reference: Path = typer.Argument(..., exists=True, dir_okay=False),
    output: Optional[Path] = typer.Option(None, "-o", "--output", dir_okay=False),
    plots: Optional[Path] = typer.Option(None, "-p", "--plots", file_okay=False),
    label_monitored: Optional[str] = "monitored",
    label_reference: Optional[str] = "reference",
    title: str = "Histogram comparison",
    _filter: str = typer.Option(".*", "-f", "--filter"),
    format: str = "pdf",
    log: str = "-",
):
    with auto_console(log) as console:
        console.print(
            Panel(
                Group(f"Monitored: {monitored}", f"Reference: {reference}"),
                title="Comparing files:",
            )
        )

        if config_path is None:
            config = Config.default()
        else:
            with config_path.open() as fh:
                config = Config(**yaml.safe_load(fh))

        console.print(Panel(Pretty(config), title="Configuration"))

        filter_path = Path(_filter)
        if filter_path.exists():
            with filter_path.open() as fh:
                filters = fh.read().strip().split("\n")
        else:
            filters = [_filter]
        comparison = compare(
            config, monitored, reference, filters=filters, console=console
        )

        comparison.label_monitored = label_monitored
        comparison.label_reference = label_reference
        comparison.title = title

        status = print_summary(comparison, console)

        if output is not None:
            if plots is not None:
                plots.mkdir(exist_ok=True, parents=True)
            make_report(comparison, output, console, plots, format=format)

        if status != Status.SUCCESS:
            raise typer.Exit(1)
