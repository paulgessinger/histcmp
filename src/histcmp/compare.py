from pathlib import Path
from typing import Tuple

from rich.progress import track
import time


from histcmp.console import console, fail, info, good, warn
from histcmp.root_helpers import integralAndError, get_bin_content
from histcmp.checks import (
    Chi2Test,
    KolmogorovTest,
    IntegralCheck,
    RatioCheck,
    ResidualCheck,
)

import ROOT


def can_handle_item(item) -> bool:
    return isinstance(item, ROOT.TH1)  # and not isinstance(item, ROOT.TH2)


def compare(a: Path, b: Path):
    rf_a = ROOT.TFile.Open(str(a))
    rf_b = ROOT.TFile.Open(str(b))

    keys_a = {k.GetName() for k in rf_a.GetListOfKeys()}
    keys_b = {k.GetName() for k in rf_b.GetListOfKeys()}

    common = keys_a.intersection(keys_b)

    removed = keys_b - keys_a
    new = keys_a - keys_b

    console.print(
        f":information: {len(common)} common elements between files", style="info"
    )

    for key in track(sorted(common), console=console, description="Comparing..."):
        console.rule(f"{key}")
        item_a = rf_a.Get(key)
        item_b = rf_b.Get(key)

        if type(item_a) != type(item_b):
            fail(
                f"Type mismatch between files for key {key}: {item_a} != {type(item_b)} => treating as both removed and newly added"
            )
            removed.add(key)
            new.add(key)

        if not can_handle_item(item_a):
            warn(f"Unable to handle item of type {type(item_a)}")
            continue

        for test in (
            KolmogorovTest,
            #  Chi2Test,
            ResidualCheck,
            IntegralCheck,
        ):
            inst = test(item_a, item_b)
            #  print(get_bin_content(item_a))
            #  print(get_bin_content(item_b))
            if inst.is_applicable():
                if inst.is_valid():
                    console.print(
                        ":white_check_mark:", inst, inst.label(), style="bold green"
                    )
                else:
                    console.print(":red_circle:", inst, inst.label(), style="bold red")
            else:
                console.print(":yellow_circle:", inst, style="yellow")

        int_a, err_a = integralAndError(item_a)
        int_b, err_b = integralAndError(item_b)

        sigma = 0
        if err_a > 0.0:
            sigma = (int_a - int_b) / err_a

        #  print(type(item_a))

    info(f"{len(removed)} elements are missing in new file")
    info(f"{len(new)} elements are added new file")
