from pathlib import Path
import ctypes
from typing import Tuple
import operator

#  from rich import print
from rich.progress import track
import time

#  import dataclasses
from abc import ABC, abstractmethod

from histcmp.console import console, fail, info, good, warn

import ROOT


class CompatCheck(ABC):
    @abstractmethod
    def is_valid(self) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def is_applicable(self) -> bool:
        raise NotImplementedError()

    @abstractmethod
    def label(self) -> str:
        raise NotImplementedError()


class ScoreThresholdTest(CompatCheck):
    def __init__(self, threshold: float, op):
        self.threshold = threshold
        self.op = op

    @abstractmethod
    def get_score() -> float:
        raise NotImplementedError()

    def is_valid(self) -> bool:
        if not self.is_applicable():
            raise RuntimeError(f"{self} not applicable, cannot check if valid")
        return self.op(self.get_score(), self.threshold)

    def label(self) -> str:
        v = "" if self.is_valid() else "! "
        return f"{v}{self.get_score()} {self._op_label()} {self.threshold}"

    def _op_label(self) -> str:
        if self.op is operator.lt:
            return "<"
        elif self.op is operator.le:
            return "<="
        elif self.op is operator.gt:
            return ">"
        elif self.op is operator.ge:
            return ">="

        return f"{self.op}"


class KolmogorovTest(ScoreThresholdTest):
    def __init__(self, item_a, item_b, threshold: float = 0.95):
        self.item_a = item_a
        self.item_b = item_b
        self.threshold = threshold

        super().__init__(threshold=threshold, op=operator.gt)

    def get_score(self) -> float:
        return self.item_a.KolmogorovTest(self.item_b)

    def is_applicable(self) -> bool:
        int_a, _ = integralAndError(self.item_a)
        int_b, _ = integralAndError(self.item_b)
        return int_a != 0 and int_b != 0

    def __str__(self) -> str:
        return "KolmogorovTest"


class Chi2Test(ScoreThresholdTest):
    def __init__(self, item_a, item_b, threshold: float = 0.01):
        self.item_a = item_a
        self.item_b = item_b
        self.threshold = threshold

        super().__init__(threshold=threshold, op=operator.lt)

    def get_score(self) -> float:
        return self.item_a.Chi2Test(self.item_b)

    def is_applicable(self) -> bool:
        int_a, _ = integralAndError(self.item_a)
        int_b, _ = integralAndError(self.item_b)
        return int_a != 0 and int_b != 0

    def __str__(self) -> str:
        return "Chi2Test"


class IntegralTest(ScoreThresholdTest):
    def __init__(self, item_a, item_b, threshold: float = 1.0):
        int_a, err_a = integralAndError(item_a)
        int_b, err_b = integralAndError(item_b)

        self.sigma = float("inf")
        if err_a > 0.0:
            self.sigma = (int_a - int_b) / err_a

        super().__init__(threshold=threshold, op=operator.lt)

    def get_score(self) -> float:
        return self.sigma

    def is_applicable(self) -> bool:
        return self.sigma != float("inf")

    def __str__(self) -> str:
        return "IntegralTest"


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

    console.print(
        f":information: {len(common)} common elements between files", style="info"
    )

    for key in track(common, console=console, description="Comparing..."):
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

        for test in (KolmogorovTest, Chi2Test, IntegralTest):
            inst = test(item_a, item_b)
            if inst.is_applicable():
                if inst.is_valid():
                    good(inst, inst.label())
                else:
                    fail(inst, inst.label())

        int_a, err_a = integralAndError(item_a)
        int_b, err_b = integralAndError(item_b)

        sigma = 0
        if err_a > 0.0:
            sigma = (int_a - int_b) / err_a

        #  print(type(item_a))

    info(f"{len(removed)} elements are missing in new file")
    info(f"{len(new)} elements are added new file")
