from pathlib import Path
from typing import Tuple, List, Any
import dataclasses

from rich.progress import track
import time


from histcmp.console import console, fail, info, good, warn
from histcmp.root_helpers import integralAndError, get_bin_content
from histcmp.checks import (
    CompatCheck,
    Chi2Test,
    KolmogorovTest,
    IntegralCheck,
    RatioCheck,
    ResidualCheck,
)

import ROOT


@dataclasses.dataclass
class ComparisonItem:
    key: str
    item_a: Any
    item_b: Any
    checks: List[CompatCheck] = []


@dataclasses.dataclass
class Comparison:
    file_a: str
    file_b: str
    common: List[ComparisonItem] = []


def can_handle_item(item) -> bool:
    return isinstance(item, ROOT.TH1) or isinstance(
        item, ROOT.TEfficiency
    )  # and not isinstance(item, ROOT.TH2)


def compare(a: Path, b: Path) -> Comparison:
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

    result = Comparison(file_a=str(a), file_b=str(b))

    for key in track(sorted(common), console=console, description="Comparing..."):

        item_a = rf_a.Get(key)
        item_b = rf_b.Get(key)

        if type(item_a) != type(item_b):
            console.rule(f"{key}")
            fail(
                f"Type mismatch between files for key {key}: {item_a} != {type(item_b)} => treating as both removed and newly added"
            )
            removed.add(key)
            new.add(key)

        console.rule(f"{key} ({item_a.__class__.__name__})")

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

    info(f"{len(removed)} elements are missing in new file")
    info(f"{len(new)} elements are added new file")

    return result
