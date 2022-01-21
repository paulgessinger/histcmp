from pathlib import Path

import typer
from wasabi import msg

app = typer.Typer()


@app.command()
def main(
    previous: Path = typer.Argument(..., exists=True, dir_okay=False),
    current: Path = typer.Argument(..., exists=True, dir_okay=False),
):
    try:
        import ROOT
    except ImportError:
        msg.fail("ROOT could not be imported")
        return

    from histcmp.compare import compare

    msg.info(f"Comparing files:")
    msg.info(f"Previous: {previous}")
    msg.info(f"Current: {current}")

    compare(previous, current)
