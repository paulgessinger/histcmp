from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.console import Group
from rich.text import Text
from rich.rule import Rule
from rich.pretty import Pretty
from rich.emoji import Emoji
import jinja2
import yaml

from histcmp.console import fail, info, console
from histcmp.report import make_report
from histcmp.checks import Status
from histcmp.config import Config
from histcmp.github import is_github_actions, github_actions_marker

#  install(show_locals=True)

app = typer.Typer()


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
):
    try:
        import ROOT
    except ImportError:
        fail("ROOT could not be imported")
        return
    ROOT.gROOT.SetBatch(ROOT.kTRUE)

    from histcmp.compare import compare

    console.print(
        Panel(
            Group(f"Monitored: {monitored}", f"Reference: {reference}"),
            title="Comparing files:",
        )
    )

    if config_path is None:
        config = Config(
            checks={
                "*": {
                    "Chi2Test": {"threshold": 0.01},
                    "KolmogorovTest": {"threshold": 0.68},
                    "RatioCheck": {"threshold": 3},
                    "ResidualCheck": {"threshold": 1},
                    "IntegralCheck": {"threshold": 3},
                }
            }
        )
    else:
        with config_path.open() as fh:
            config = Config(**yaml.safe_load(fh))

    console.print(Panel(Pretty(config), title="Configuration"))

    try:
        filter_path = Path(_filter)
        if filter_path.exists():
            with filter_path.open() as fh:
                filters = fh.read().strip().split("\n")
        else:
            filters = [_filter]
        comparison = compare(config, monitored, reference, filters=filters)

        comparison.label_monitored = label_monitored
        comparison.label_reference = label_reference
        comparison.title = title

        #  console.print(
        #  Panel(
        #  Text(        f":information: {len(common)} common elements between files", style="info")
        #  Text(        f":information: {len(result.a_only)} only found in file a", style="info")
        #  Text(        f":information: {len(result.b_only)} common elements between files", style="info")
        #  )
        #  )

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

        if (
            len(failures) > 0
            or len(comparison.a_only) > 0
            or len(comparison.b_only) > 0
        ):
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
                    Text(
                        f"{Emoji.replace(status.icon)} {status.name}", justify="center"
                    ),
                    *msg,
                ),
                style=style,
            )
        )

        if output is not None:
            if plots is not None:
                plots.mkdir(exist_ok=True, parents=True)
            make_report(comparison, output, plots, format=format)

        if status != Status.SUCCESS:
            raise typer.Exit(1)

    except Exception as e:
        if isinstance(e, jinja2.exceptions.TemplateRuntimeError):
            raise e
        raise
        #  console.print_exception(show_locals=True)
