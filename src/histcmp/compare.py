from pathlib import Path
from typing import Tuple, List, Any
import functools

from rich.progress import track
from pydantic import BaseModel


from histcmp.console import console, fail, info, good, warn
from histcmp.root_helpers import integralAndError, get_bin_content
from histcmp.checks import (
    CompatCheck,
    Chi2Test,
    KolmogorovTest,
    IntegralCheck,
    RatioCheck,
    ResidualCheck,
    Status,
)

import ROOT


class ComparisonItem(BaseModel):
    class Config:
        arbitrary_types_allowed = True
        keep_untouched = (functools.cached_property,)

    key: str
    item_a: Any
    item_b: Any
    checks: List[CompatCheck] = []

    @functools.cached_property
    def status(self) -> Status:
        statuses = [c.status for c in self.checks]
        if any(s == Status.FAILURE for s in statuses):
            return Status.FAILURE
        if all(s == Status.SUCCESS for s in statuses):
            return Status.SUCCESS
        if any(s == Status.SUCCESS for s in statuses):
            return Status.SUCCESS

        return Status.INCONCLUSIVE
        #  raise RuntimeError("Shouldn't happen")

    def ensure_plots(self, output: Path):
        for check in self.checks:
            check.ensure_plot(self.key, output)


class Comparison(BaseModel):
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

        item = ComparisonItem(key=key, item_a=item_a, item_b=item_b)

        for test in (
            KolmogorovTest,
            RatioCheck,
            #  Chi2Test,
            ResidualCheck,
            IntegralCheck,
        ):
            inst = test(item_a, item_b)
            item.checks.append(inst)
            if inst.is_applicable():
                if inst.is_valid():
                    console.print(
                        ":white_check_mark:", inst, inst.label(), style="bold green"
                    )
                else:
                    console.print(":red_circle:", inst, inst.label(), style="bold red")
            else:
                console.print(":yellow_circle:", inst, style="yellow")
        result.common.append(item)

    info(f"{len(removed)} elements are missing in new file")
    info(f"{len(new)} elements are added new file")

    return result
