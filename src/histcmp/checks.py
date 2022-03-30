import numpy
import operator
from abc import ABC, abstractmethod, abstractproperty
import collections
from pathlib import Path
import ctypes
import functools
from enum import Enum
from typing import Tuple, Optional, List
import warnings

import ROOT

from histcmp import icons
from histcmp.root_helpers import (
    integralAndError,
    get_bin_content,
    get_bin_content_error,
    push_root_level,
    convert_hist,
    tefficiency_to_th1,
)


class Status(Enum):
    SUCCESS = 1
    FAILURE = 2
    INCONCLUSIVE = 3
    #  DISABLED = 4

    @property
    def icon(self):
        if self == Status.SUCCESS:
            return icons.success
        elif self == Status.INCONCLUSIVE:
            return icons.inconclusive
        #  elif self == Status.DISABLED:
        #  return icons.disabled
        else:
            return icons.failure


ROOT.gInterpreter.Declare(
    """
auto MyChi2Test(const TH1* a, const TH1* b, Option_t* option){
   Double_t chi2 = 0;
   Int_t ndf = 0, igood = 0;
   Double_t* res = 0;

   TString opt = option;
   opt.ToUpper();

   Double_t prob = a->Chi2TestX(b,chi2,ndf,igood,option,res);

   return std::make_tuple(prob, chi2, ndf, igood, res);
}
"""
)


chi2result = collections.namedtuple(
    "chi2result", ["prob", "chi2", "ndf", "igood", "res"]
)


class CompatCheck(ABC):
    def __init__(self, disabled: bool = False, suffix: Optional[str] = None):
        self.disabled = disabled
        self._plot = None
        self.suffix = suffix

    @property
    def is_disabled(self) -> bool:
        return self.disabled

    @abstractproperty
    def is_valid(self) -> bool:
        raise NotImplementedError()

    @abstractproperty
    def is_applicable(self) -> bool:
        raise NotImplementedError()

    @abstractproperty
    def label(self) -> str:
        raise NotImplementedError()

    @property
    def status(self) -> Status:
        if not self.is_applicable:
            return Status.INCONCLUSIVE
        elif self.is_valid:
            return Status.SUCCESS
        else:
            return Status.FAILURE

    def make_plot(self, output: Path) -> bool:
        return False

    def ensure_plot(self, key: str, report_dir: Path, plot_dir: Path) -> Optional[Path]:
        if self._plot is not None:
            return self._plot
        rel_path = plot_dir / f"{key}_{self}.png"
        if (report_dir / rel_path).exists():
            self._plot = rel_path
            return self._plot
        if self.make_plot(report_dir / rel_path):
            self._plot = rel_path
        return self._plot

    @property
    def plot(self) -> Optional[Path]:
        return self._plot

    @abstractproperty
    def name(self) -> str:
        raise NotImplementedError()

    def __str__(self) -> str:
        return self.name + (" " + self.suffix if self.suffix is not None else "")


class CompositeCheck(CompatCheck):
    def __init__(self, *args: List[CompatCheck], **kwargs):
        super().__init__(**kwargs)
        self.checks = args

        self.disabled = any(c.is_disabled for c in self.checks)

    @property
    def is_applicable(self) -> bool:
        return all(c.is_applicable for c in self.checks)

    @property
    def is_valid(self) -> bool:
        return all(c.is_valid for c in self.checks)

    @property
    def label(self) -> str:
        return " --- ".join(c.label for c in self.checks)

    @property
    def name(self) -> str:
        return " + ".join(str(c) for c in self.checks)


class ScoreThresholdCheck(CompatCheck):
    def __init__(self, threshold: float, op, **kwargs):
        self.threshold = threshold
        self.op = op
        super().__init__(**kwargs)

    @abstractproperty
    def score(self) -> float:
        raise NotImplementedError()

    @functools.cached_property
    def is_valid(self) -> bool:
        if not self.is_applicable:
            raise RuntimeError(f"{self} not applicable, cannot check if valid")
        return self.op(self.score, self.threshold)

    @property
    def label(self) -> str:
        v = "" if self.is_valid else "! "
        return f"{v}{self.score} {self._op_label()} {self.threshold}"

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


class KolmogorovTest(ScoreThresholdCheck):
    def __init__(self, item_a, item_b, threshold: float = 0.68, **kwargs):
        self.item_a = item_a
        self.item_b = item_b
        self.threshold = threshold

        super().__init__(threshold=threshold, op=operator.gt, **kwargs)

    @functools.cached_property
    def score(self) -> float:
        return self.item_a.KolmogorovTest(self.item_b)

    @functools.cached_property
    def is_applicable(self) -> bool:
        with push_root_level(ROOT.kError):
            if isinstance(self.item_a, ROOT.TEfficiency):
                self.item_a = tefficiency_to_th1(self.item_a)
                self.item_b = tefficiency_to_th1(self.item_b)

        int_a, _ = integralAndError(self.item_a)
        int_b, _ = integralAndError(self.item_b)
        return int_a != 0 and int_b != 0

    @property
    def name(self) -> str:
        return "KolmogorovTest"


class Chi2Test(ScoreThresholdCheck):
    def __init__(self, item_a, item_b, threshold: float = 0.01, **kwargs):
        self.item_a = item_a
        self.item_b = item_b
        self.threshold = threshold

        if isinstance(self.item_a, ROOT.TEfficiency):
            with push_root_level(ROOT.kError):
                self.item_a = tefficiency_to_th1(self.item_a)
                self.item_b = tefficiency_to_th1(self.item_b)

        super().__init__(threshold=threshold, op=operator.gt, **kwargs)

    @functools.cached_property
    def _result_v(self):
        opt = "P"
        with push_root_level(ROOT.kWarning):
            self._result_v = chi2result(*ROOT.MyChi2Test(self.item_a, self.item_b, opt))

        return self._result_v

    @property
    def score(self) -> float:
        res = self._result_v
        return res.prob

    @functools.cached_property
    def is_applicable(self) -> bool:
        int_a, _ = integralAndError(self.item_a)
        int_b, _ = integralAndError(self.item_b)
        if int_a == 0 or int_b == 0:
            return False

        res = self._result_v
        if res.ndf == -1:
            return False

        if res.prob == 0.0:
            return False

        return True

    @property
    def name(self) -> str:
        return "Chi2Test"


class IntegralCheck(ScoreThresholdCheck):
    def __init__(self, item_a, item_b, threshold: float = 3.0, **kwargs):
        super().__init__(threshold=threshold, op=operator.lt, **kwargs)
        self.sigma = float("inf")
        if not isinstance(item_a, ROOT.TH1) and not isinstance(
            item_a, ROOT.TEfficiency
        ):
            return

        #  int_a, err_a = integralAndError(item_a)
        #  int_b, err_b = integralAndError(item_b)

        if isinstance(item_a, ROOT.TEfficiency):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                item_a = tefficiency_to_th1(item_a)
                item_b = tefficiency_to_th1(item_b)

        self.int_a, self.err_a = integralAndError(item_a)
        self.int_b, self.err_b = integralAndError(item_b)

        if self.err_a > 0.0:
            self.sigma = numpy.abs(self.int_a - self.int_b) / numpy.sqrt(
                self.err_a ** 2 + self.err_b ** 2
            )

    @property
    def score(self) -> float:
        return self.sigma

    @property
    def label(self) -> str:
        cmp = "<" if self.is_valid else ">="
        return f"Intregal: {self.int_a}+-{self.err_a:} vs. {self.int_b}+-{self.err_b}: (int_a - int_b) / sqrt(sigma(int_a)^2 + sigma(int_b)^2) = {self.sigma:.2f} {cmp} {self.threshold}"

    @functools.cached_property
    def is_applicable(self) -> bool:
        return self.sigma != float("inf")

    @property
    def name(self) -> str:
        return "IntegralTest"


class RatioCheck(CompatCheck):
    def __init__(self, item_a, item_b, threshold: float = 3, **kwargs):
        self.ratio = None
        self.ratio_err = None
        self.ratio_pull = None
        self.threshold = threshold

        super().__init__(**kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            if isinstance(item_a, ROOT.TEfficiency):
                a, a_err = convert_hist(item_a)
                b, b_err = convert_hist(item_b)
                ratio = a.values() / b.values()

                a_err = 0.5 * (a_err[0] + a_err[1])
                b_err = 0.5 * (b_err[0] + b_err[1])

                self.ratio_err = numpy.sqrt(
                    (a_err / b.values()) ** 2
                    + (a.values() / b.values() ** 2 * b_err) ** 2
                )

                self.ratio = a.values() / b.values()
                self.applicable = True

            else:
                if isinstance(item_a, ROOT.TProfile):
                    item_a = item_a.ProjectionX()
                    item_b = item_b.ProjectionX()

                try:
                    ratio = item_a.Clone()
                    ratio.SetDirectory(0)
                    ratio.Divide(item_b)
                    self.ratio, self.ratio_err = get_bin_content_error(ratio)
                    self.applicable = True
                except Exception:
                    self.applicable = False

            if self.applicable:
                ratio, err = self.ratio, self.ratio_err
                m = (ratio != 0.0) & (~numpy.isnan(ratio)) & (err != 0.0)
                ratio[m] = ratio[m] - 1
                self.ratio_pull = ratio[m] / err[m]

    @functools.cached_property
    def is_applicable(self) -> bool:
        if self.ratio_pull is not None:
            nbins = len(self.ratio_pull)
            if nbins == 0:
                return False
        return self.applicable and self.ratio is not None

    @property
    def is_valid(self) -> bool:
        nabove = numpy.sum(numpy.abs(self.ratio_pull) >= self.threshold)
        nbins = len(self.ratio_pull)

        return nabove < numpy.sqrt(nbins)

    @property
    def label(self) -> str:
        n = numpy.sum(numpy.abs(self.ratio_pull) >= self.threshold)
        nbins = len(self.ratio_pull)
        return f"(a/b - 1) / sigma(a/b) > {self.threshold} for {n}/{nbins} bins, cf. {numpy.sqrt(nbins)}"

    @property
    def name(self) -> str:
        return "RatioCheck"


class ResidualCheck(CompatCheck):
    def __init__(self, item_a, item_b, threshold=1, **kwargs):
        self.threshold = threshold
        self.item_a = item_a
        self.item_b = item_b

        super().__init__(**kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            if isinstance(self.item_a, ROOT.TEfficiency):
                with push_root_level(ROOT.kError):
                    self.item_a = tefficiency_to_th1(self.item_a)
                    self.item_b = tefficiency_to_th1(self.item_b)

            if isinstance(self.item_a, ROOT.TProfile):
                self.item_a = self.item_a.ProjectionX()
                self.item_b = self.item_b.ProjectionX()

            try:
                self.residual = self.item_a.Clone()
                self.residual.SetDirectory(0)
                self.residual.Add(self.item_b, -1)

                self.applicable = True
            except Exception:
                self.applicable = False

    def is_applicable(self) -> bool:
        val, err, pull = self._pulls
        if numpy.sum(~numpy.isnan(pull)) == 0:
            return False
        return self.applicable

    @functools.cached_property
    def _pulls(self):
        val, _ = get_bin_content_error(self.residual)
        _, err_a = get_bin_content_error(self.item_a)
        _, err_b = get_bin_content_error(self.item_b)
        err = numpy.sqrt(err_a ** 2 + err_b ** 2)
        m = err > 0
        pull = numpy.zeros_like(val)
        pull[m] = numpy.abs(val[m]) / err[m]
        return val, err, pull

    @functools.cached_property
    def is_valid(self) -> bool:
        val, err, pull = self._pulls
        nabove = numpy.sum(pull[~numpy.isnan(pull)] >= self.threshold)
        return nabove < numpy.sqrt(len(val))

    @functools.cached_property
    def label(self) -> str:
        val, err, pull = self._pulls
        count = numpy.sum(pull[~numpy.isnan(pull)] >= self.threshold)
        pe = numpy.sqrt(len(val))
        if self.is_valid:
            return (
                f"pull < {self.threshold} in {len(val)-count}/{len(val)} bins, cf. {pe}"
            )
        else:
            return f"pull > {self.threshold} in {count}/{len(val)} bins, cf. {pe}"

    def make_plot(self, output: Path) -> bool:
        if not self.applicable:
            return False
        c = ROOT.TCanvas("c1", "c1")

        opt = ""
        if isinstance(self.residual, ROOT.TH2):
            opt = "colz"
        self.residual.Draw(opt)
        self.residual.GetYaxis().SetTitle("reference / current")
        c.SaveAs(str(output))
        return True

    @property
    def name(self) -> str:
        return "ResidualCheck"
