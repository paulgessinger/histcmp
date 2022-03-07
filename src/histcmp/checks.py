import numpy
import operator
from abc import ABC, abstractmethod, abstractproperty
import collections
from pathlib import Path
import ctypes
import functools
from enum import Enum
from typing import Tuple, Optional

import ROOT

from histcmp import icons
from histcmp.root_helpers import (
    integralAndError,
    get_bin_content,
    get_bin_content_error,
    push_root_level,
    convert_hist,
)


class Status(Enum):
    SUCCESS = 1
    FAILURE = 2
    INCONCLUSIVE = 3

    @property
    def icon(self):
        if self == Status.SUCCESS:
            return icons.success
        elif self == Status.INCONCLUSIVE:
            return icons.inconclusive
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
    def __init__(self):
        self._plot = None

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
        if self.is_valid:
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


class ScoreThresholdCheck(CompatCheck):
    def __init__(self, threshold: float, op):
        self.threshold = threshold
        self.op = op
        super().__init__()

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
    def __init__(self, item_a, item_b, threshold: float = 0.68):
        self.item_a = item_a
        self.item_b = item_b
        self.threshold = threshold

        super().__init__(threshold=threshold, op=operator.gt)

    @functools.cached_property
    def score(self) -> float:
        return self.item_a.KolmogorovTest(self.item_b)

    @functools.cached_property
    def is_applicable(self) -> bool:
        if isinstance(self.item_a, ROOT.TEfficiency):
            passed = self.item_a.GetPassedHistogram()
            total = self.item_a.GetTotalHistogram()
            self.item_a = passed.Clone()
            self.item_a.Divide(total)

            passed = self.item_b.GetPassedHistogram()
            total = self.item_b.GetTotalHistogram()
            self.item_b = passed.Clone()
            self.item_b.SetDirectory(0)
            self.item_b.Divide(total)
        int_a, _ = integralAndError(self.item_a)
        int_b, _ = integralAndError(self.item_b)
        return int_a != 0 and int_b != 0

    def __str__(self) -> str:
        return "KolmogorovTest"


class Chi2Test(ScoreThresholdCheck):
    def __init__(self, item_a, item_b, threshold: float = 0.01):
        self.item_a = item_a
        self.item_b = item_b
        self.threshold = threshold

        if isinstance(self.item_a, ROOT.TEfficiency):
            passed = self.item_a.GetPassedHistogram()
            total = self.item_a.GetTotalHistogram()
            self.item_a = passed.Clone()
            self.item_a.Divide(total)

            passed = self.item_b.GetPassedHistogram()
            total = self.item_b.GetTotalHistogram()
            self.item_b = passed.Clone()
            self.item_b.SetDirectory(0)
            self.item_b.Divide(total)

        super().__init__(threshold=threshold, op=operator.gt)

    @functools.cached_property
    def _result_v(self):
        opt = "P"
        with push_root_level(ROOT.kWarning):

            self._result_v = chi2result(*ROOT.MyChi2Test(self.item_a, self.item_b, opt))
            #  print(self._result_v)
            #  nbins = self.item_a.GetXaxis().GetNbins() - 2
            #  arr = self._result_v.res
            #  arr.reshape((nbins,))
            #  v = numpy.frombuffer(arr, dtype=numpy.float64, count=nbins)
            #  print(v)
            #  print(self._result_v.res)

            #  prob = self.item_a.Chi2TestX(
            #  self.item_b, chi2, ndf, igood, opt, ctypes.pointer(res)
            #  )

            #  return self.item_a.Chi2Test(self.item_b, opt)

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
        #  if res.igood != 0:
        #  return False
        if res.ndf == -1:
            return False

        #  if res.igood != 0 and res.prob == 0.0: return False
        if res.prob == 0.0: return False

        #  sumw2 = numpy.array(
        #  [
        #  self.item_a.GetSumw2().At(b)
        #  for b in range(1, self.item_a.GetXaxis().GetNbins())
        #  ]
        #  )
        #  print(
        #  numpy.sum(numpy.sqrt(sumw2)),
        #  self.item_a.GetSumOfWeights(),
        #  )

        #  print(get_bin_content(self.item_a))
        #  print(get_bin_content(self.item_b))

        return True

    def __str__(self) -> str:
        return "Chi2Test"


class IntegralCheck(ScoreThresholdCheck):
    def __init__(self, item_a, item_b, threshold: float = 3.0):
        super().__init__(threshold=threshold, op=operator.lt)
        self.sigma = float("inf")
        if not isinstance(item_a, ROOT.TH1) and not isinstance(
            item_a, ROOT.TEfficiency
        ):
            return

        #  int_a, err_a = integralAndError(item_a)
        #  int_b, err_b = integralAndError(item_b)

        if isinstance(item_a, ROOT.TEfficiency):
            passed = item_a.GetPassedHistogram()
            total = item_a.GetTotalHistogram()
            item_a = passed.Clone()
            item_a.Divide(total)

            passed = item_b.GetPassedHistogram()
            total = item_b.GetTotalHistogram()
            item_b = passed.Clone()
            item_b.SetDirectory(0)
            item_b.Divide(total)
        self.int_a, self.err_a = integralAndError(item_a)
        self.int_b, self.err_b = integralAndError(item_b)

        if self.err_a > 0.0:
            self.sigma = numpy.abs(self.int_a - self.int_b) / self.err_a

    @property
    def score(self) -> float:
        return self.sigma

    @property
    def label(self) -> str:
        cmp = "<" if self.is_valid else ">="
        return f"Intregal: {self.int_a}+-{self.err_a:} vs. {self.int_b}+-{self.err_b}: (int_a - int_b) / sigma(int_a) = {self.sigma:.2f} {cmp} {self.threshold}"

    @functools.cached_property
    def is_applicable(self) -> bool:
        return self.sigma != float("inf")

    def __str__(self) -> str:
        return "IntegralTest"


class RatioCheck(CompatCheck):
    def __init__(self, item_a, item_b, threshold: float = 3):
        #  self.val_a, self.err_a = get_bin_content_error(item_a)
        #  self.val_b, self.err_b = get_bin_content_error(item_b)
        #  self.ratio = self.val_a / self.val_b
        self.ratio = None
        self.threshold = threshold

        super().__init__()

        if isinstance(item_a, ROOT.TEfficiency):
            passed = item_a.GetPassedHistogram()
            total = item_a.GetTotalHistogram()
            item_a = passed.Clone()
            item_a.Divide(total)

            passed = item_b.GetPassedHistogram()
            total = item_b.GetTotalHistogram()
            item_b = passed.Clone()
            item_b.SetDirectory(0)
            item_b.Divide(total)

        elif isinstance(item_a, ROOT.TProfile):
            item_a = item_a.ProjectionX()
            item_b = item_b.ProjectionX()

        try:
            ratio = item_a.Clone()
            ratio.SetDirectory(0)
            ratio.Divide(item_b)
            #  print(get_bin_content(item_a))
            #  print(get_bin_content(item_b))
            self.applicable = True
            self.ratio = ratio
        except Exception:
            self.applicable = False

    def make_plot(self, output: Path) -> bool:
        if not self.applicable:
            return False
        c = ROOT.TCanvas("c1", "c1")

        opt = ""
        if isinstance(self.ratio, ROOT.TH2):
            opt = "colz"
        self.ratio.Draw(opt)
        self.ratio.GetYaxis().SetTitle("reference / current")
        self.ratio.GetYaxis().SetRangeUser(0.5, 2)
        c.SaveAs(str(output))
        return True

    @functools.cached_property
    def is_applicable(self) -> bool:
        nbins = len(self._ratio())
        if nbins == 0: return False
        return self.applicable and self.ratio is not None

    @functools.lru_cache(1)
    def _ratio(self):
        ratio, err = get_bin_content_error(self.ratio)
        #  print(ratio, err)
        m = ratio != 0.0
        ratio[m] = ratio[m] - 1

        me = err != 0.0

        return ratio[m & me] / err[m & me]

    @property
    def is_valid(self) -> bool:
        #  print("ratio:", self._ratio())
        nabove = numpy.sum(numpy.abs(self._ratio()) < self.threshold)
        nbins = len(self._ratio())
        
        return nabove > numpy.sqrt(nbins)

    @property
    def label(self) -> str:
        n = numpy.sum(numpy.abs(self._ratio()) >= self.threshold)
        nbins = len(self._ratio())
        return f"(a/b - 1) / sigma(a/b) > {self.threshold} for {n}/{nbins} bins, cf. {numpy.sqrt(nbins)}"

    def __str__(self) -> str:
        return "RatioCheck"


class ResidualCheck(CompatCheck):
    def __init__(self, item_a, item_b, threshold=3):
        self.threshold = threshold
        self.item_a = item_a
        self.item_b = item_b

        super().__init__()

        if isinstance(self.item_a, ROOT.TEfficiency):
            self.item_a = self.item_a.CreateGraph().GetHistogram()
            self.item_b = self.item_b.CreateGraph().GetHistogram()
        if isinstance(self.item_a, ROOT.TProfile):
            self.item_a = self.item_a.ProjectionX()
            self.item_b = self.item_b.ProjectionX()

        try:
            self.residual = self.item_a.Clone()
            self.residual.SetDirectory(0)
            #  print(*get_bin_content_error(self.residual))
            #  print(*get_bin_content_error(self.item_b))
            self.residual.Add(self.item_b, -1)
            #  print(*get_bin_content_error(self.residual))

            self.applicable = True
        except Exception:
            self.applicable = False

    def is_applicable(self) -> bool:
        val, err, pull = self._pulls
        if numpy.sum(~numpy.isnan(pull)) == 0: return False
        return self.applicable

    @functools.cached_property
    def _pulls(self):
        val, err = get_bin_content_error(self.residual)
        m = err > 0
        pull = numpy.zeros_like(val)
        pull[m] = numpy.abs(val[m]) / err[m]
        return val, err, pull

    @functools.cached_property
    def is_valid(self) -> bool:
        val, err, pull = self._pulls
        nabove= numpy.sum(pull[~numpy.isnan(pull)] < self.threshold)
        return nabove > numpy.sqrt(len(val))

    @functools.cached_property
    def label(self) -> str:
        val, err, pull = self._pulls
        count = numpy.sum(pull[~numpy.isnan(pull)] >= self.threshold)
        pe = numpy.sqrt(len(val))
        if self.is_valid:
            return f"pull < {self.threshold} in {len(val)-count} bins, cf. {pe}"
        else:
            return f"pull > {self.threshold} in {count} bins, cf. {pe}"

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

    def __str__(self) -> str:
        return "ResidualCheck"
