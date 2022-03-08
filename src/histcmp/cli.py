from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.text import Text
from rich.emoji import Emoji
import jinja2
import yaml

from histcmp.console import fail, info, console
from histcmp.report import make_report
from histcmp.checks import Status
from histcmp.config import Config

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
):
    try:
        import ROOT
    except ImportError:
        fail("ROOT could not be imported")
        return
    ROOT.gROOT.SetBatch(ROOT.kTRUE)

    from histcmp.compare import compare

    info(f"Comparing files:")
    info(f"Monitored: {monitored}")
    info(f"Reference: {reference}")

    if config_path is None:
        config = Config(
            checks={
                "*": {
                    k: None
                    for k in [
                        "Chi2Test",
                        "KolmogorovTest",
                        "RatioCheck",
                        "ResidualCheck",
                        "IntegralCheck",
                    ]
                }
            }
        )
    else:
        with config_path.open() as fh:
            config = Config(**yaml.safe_load(fh))

    print(config)

    try:
        comparison = compare(config, monitored, reference)

        if output is not None:
            make_report(comparison, output)

        status = Status.SUCCESS
        style = "bold green"

        if any(c.status == Status.FAILURE for c in comparison.common):
            status = Status.FAILURE
            style = "bold red"
        if all(c.status == Status.INCONCLUSIVE for c in comparison.common):
            status = Status.INCONCLUSIVE
            style = "bold yellow"

        console.print(
            Panel(
                Text(f"{Emoji.replace(status.icon)} {status.name}", justify="center"),
                style=style,
            )
        )

        if status != Status.SUCCESS:
            raise typer.Exit(1)

    except Exception as e:
        if isinstance(e, jinja2.exceptions.TemplateRuntimeError):
            raise e
        raise
        #  console.print_exception(show_locals=True)
