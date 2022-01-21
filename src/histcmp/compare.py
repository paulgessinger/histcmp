from pathlib import Path
import ctypes
from typing import Tuple

from wasabi import msg

import ROOT


def can_handle_item(item) -> bool:
    return isinstance(item, ROOT.TH1) and not isinstance(item, ROOT.TH2)


def integralAndError(item) -> Tuple[float, float]:
    e = ctypes.c_double(-1)
    i = item.IntegralAndError(0, item.GetXaxis().GetNbins(), e)
    return i, e.value


def compare(a: Path, b: Path):
    rf_a = ROOT.TFile.Open(str(a))
    rf_b = ROOT.TFile.Open(str(b))

    keys_a = {k.GetName() for k in rf_a.GetListOfKeys()}
    keys_b = {k.GetName() for k in rf_b.GetListOfKeys()}

    common = keys_a.intersection(keys_b)

    removed = keys_b - keys_a
    new = keys_a - keys_b

    msg.info(f"{len(common)} common elements between files")

    for key in common:
        item_a = rf_a.Get(key)
        item_b = rf_b.Get(key)

        if type(item_a) != type(item_b):
            msg.fail(
                f"Type mismatch between files for key {key}: {item_a} != {type(item_b)} => treating as both removed and newly added"
            )
            removed.add(key)
            new.add(key)

        if not can_handle_item(item_a):
            msg.warn(f"Unable to handle item of type {type(item_a)}")
            continue

        if any(h.IsEmpty() for h in (item_a, item_b)):
            msg.warn("One input is empty")

        chi2 = item_a.Chi2Test(item_b)
        kolmo = item_a.KolmogorovTest(item_b)
        print(key, "chi2", chi2, "kolmo", kolmo)

        #  e = ctypes.c_double(-1)
        #  i = item_a.IntegralAndError(0, item_a.GetXaxis().GetNbins(), e)
        i, e = integralAndError(item_a)
        print(i, e)

        #  print(type(item_a))

    msg.info(f"{len(removed)} elements are missing in new file")
    msg.info(f"{len(new)} elements are added new file")
