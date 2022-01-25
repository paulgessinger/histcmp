from pathlib import Path
from typing import Optional

import typer
from rich.traceback import install
import jinja2

from histcmp.console import fail, info, console
from histcmp.report import make_report

#  install(show_locals=True)

app = typer.Typer()


@app.command()
def main(
    previous: Path = typer.Argument(..., exists=True, dir_okay=False),
    current: Path = typer.Argument(..., exists=True, dir_okay=False),
    output: Optional[Path] = typer.Option(None, "-o", "--output", file_okay=False),
):
    try:
        import ROOT
    except ImportError:
        fail("ROOT could not be imported")
        return

    from histcmp.compare import compare

    info(f"Comparing files:")
    info(f"Previous: {previous}")
    info(f"Current: {current}")

    try:
        comparison = compare(previous, current)

        if output is not None:
            if not output.exists():
                output.mkdir()
            make_report(comparison, output)
    except Exception as e:
        if isinstance(e, jinja2.exceptions.TemplateRuntimeError):
            raise e
        raise
        #  console.print_exception(show_locals=True)
