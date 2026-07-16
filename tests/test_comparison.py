from pathlib import Path

import pytest
import typer

import histcmp.cli

def test_comparison_ckf_main():
    monitored = Path(__file__).parent / "data" / "performance_ckf.root"
    reference = Path(__file__).parent / "data" / "performance_ckf_main.root"
    assert monitored.exists(), f"File {monitored} does not exist"
    assert reference.exists(), f"File {reference} does not exist"

    with pytest.raises(typer.Exit):
        histcmp.cli.main(monitored, reference)

    histcmp.cli.main(monitored, monitored)
    histcmp.cli.main(reference, reference)
