from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def main(
    previous: Path = typer.Argument(..., exists=True, dir_okay=False),
    current: Path = typer.Argument(..., exists=True, dir_okay=False),
):
    print("hi")
