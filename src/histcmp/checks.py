import numpy
import operator
from abc import ABC, abstractmethod
import collections
import ctypes
import functools

import ROOT

from histcmp.root_helpers import (
    integralAndError,
    get_bin_content,
    get_bin_content_error,
)

ROOT.gInterpreter.Declare(
    """
auto MyChi2Test(const TH1* a, const TH1* b, Option_t* option){
   Double_t chi2 = 0;
   Int_t ndf = 0, igood = 0;
   Double_t* res = 0;

   TString opt = option;
   opt.ToUpper();

   Double_t prob = a->Chi2TestX(b,chi2,ndf,igood,option,res);

   return std::tuple{prob, chi2, ndf, igood, res};
}
"""
)


chi2result = collections.namedtuple(
    "chi2result", ["prob", "chi2", "ndf", "igood", "res"]
)


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


class ScoreThresholdCheck(CompatCheck):
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


class KolmogorovTest(ScoreThresholdCheck):
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


class Chi2Test(ScoreThresholdCheck):
    def __init__(self, item_a, item_b, threshold: float = 0.01):
        self.item_a = item_a
        self.item_b = item_b
        self.threshold = threshold
        self._result_v = None

        super().__init__(threshold=threshold, op=operator.gt)

    def _result(self):
        if self._result_v is None:
            opt = "P"
            error_ignore = ROOT.gErrorIgnoreLevel
            try:
                ROOT.gErrorIgnoreLevel = ROOT.kWarning

                self._result_v = chi2result(
                    *ROOT.MyChi2Test(self.item_a, self.item_b, opt)
                )
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
            finally:
                ROOT.gErrorIgnoreLevel = error_ignore

        return self._result_v

    def get_score(self) -> float:
        res = self._result()
        return res.prob

    def is_applicable(self) -> bool:
        int_a, _ = integralAndError(self.item_a)
        int_b, _ = integralAndError(self.item_b)
        if int_a == 0 or int_b == 0:
            return False

        res = self._result()
        #  if res.igood != 0:
        #  return False
        if res.ndf == -1:
            return False

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
    def __init__(self, item_a, item_b, threshold: float = 1.0):
        int_a, err_a = integralAndError(item_a)
        int_b, err_b = integralAndError(item_b)

        self.sigma = float("inf")
        if err_a > 0.0:
            self.sigma = numpy.abs(int_a - int_b) / err_a

        super().__init__(threshold=threshold, op=operator.lt)

    def get_score(self) -> float:
        return self.sigma

    def is_applicable(self) -> bool:
        return self.sigma != float("inf")

    def __str__(self) -> str:
        return "IntegralTest"


class RatioCheck(CompatCheck):
    def __init__(self, item_a, item_b):
        #  self.val_a, self.err_a = get_bin_content_error(item_a)
        #  self.val_b, self.err_b = get_bin_content_error(item_b)
        #  self.ratio = self.val_a / self.val_b

        try:
            self.ratio = item_a.Clone()
            self.ratio.Divide(item_b)
            self.applicable = True
        except Exception:
            self.applicable = False

    def is_applicable(self) -> bool:
        return self.applicable

    def is_valid(self) -> bool:
        raise NotImplemented()
        ratio, err = get_bin_content_error(self.ratio)
        print(ratio)
        print(err)
        return False

    def label(self) -> str:
        return "ratio"

    def __str__(self) -> str:
        return "RatioCheck"


class ResidualCheck(CompatCheck):
    def __init__(self, item_a, item_b, threshold=1):
        self.threshold = threshold

        try:
            self.residual = item_a.Clone()
            self.residual.Add(item_b, -1)
            self.applicable = True
        except Exception:
            raise
            self.applicable = False

    def is_applicable(self) -> bool:
        return self.applicable

    @functools.cached_property
    def _pulls(self):
        val, err = get_bin_content_error(self.residual)
        m = err > 0
        pull = numpy.zeros_like(val)
        pull[m] = numpy.abs(val[m]) / err[m]
        return val, err, pull

    def is_valid(self) -> bool:
        val, err, pull = self._pulls
        return numpy.all(pull[~numpy.isnan(pull)] < self.threshold)

    def label(self) -> str:
        if self.is_valid():
            return f"residuals < {self.threshold}"
        else:
            return f"residuals > {self.threshold}"

    def __str__(self) -> str:
        return "ResidualCheck"