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
from cppyy.gbl.std import get

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


def chi2_test_x(h1, h2, option="UU"):
    """
    Python implementation of ROOT's Chi2TestX function.
    
    Parameters:
    -----------
    h1, h2 : ROOT.TH1
        The histograms to compare
    option : str
        Options for the test:
        - "UU" = experiment experiment comparison (unweighted-unweighted)
        - "UW" = experiment MC comparison (unweighted-weighted)
        - "WW" = MC MC comparison (weighted-weighted)
        - "NORM" = if one or both histograms is scaled
        - "OF" = overflows included
        - "UF" = underflows included
    
    Returns:
    --------
    tuple: (prob, chi2, ndf, igood)
        prob: p-value of the test
        chi2: chi-square value
        ndf: number of degrees of freedom
        igood: test output status
            - igood=0 - no problems
            - For unweighted unweighted comparison:
                - igood=1: There is a bin in the 1st histogram with less than 1 event
                - igood=2: There is a bin in the 2nd histogram with less than 1 event
                - igood=3: When conditions for igood=1 and igood=2 are satisfied
            - For unweighted weighted comparison:
                - igood=1: There is a bin in the 1st histogram with less than 1 event
                - igood=2: There is a bin in the 2nd histogram with less than 10 effective events
                - igood=3: When conditions for igood=1 and igood=2 are satisfied
    """
    # Initialize variables
    chi2 = 0.0
    ndf = 0
    igood = 0
    
    # Check dimensions
    if h1.GetDimension() != h2.GetDimension():
        print("Error: Histograms have different dimensions")
        return 0.0, 0.0, 0, 0
    
    # Get axes
    xaxis1 = h1.GetXaxis()
    xaxis2 = h2.GetXaxis()
    yaxis1 = h1.GetYaxis()
    yaxis2 = h2.GetYaxis()
    zaxis1 = h1.GetZaxis()
    zaxis2 = h2.GetZaxis()
    
    # Get number of bins
    nbinx1 = xaxis1.GetNbins()
    nbinx2 = xaxis2.GetNbins()
    nbiny1 = yaxis1.GetNbins()
    nbiny2 = yaxis2.GetNbins()
    nbinz1 = zaxis1.GetNbins()
    nbinz2 = zaxis2.GetNbins()
    
    # Check number of channels
    if nbinx1 != nbinx2 or nbiny1 != nbiny2 or nbinz1 != nbinz2:
        print("Error: Histograms have different number of bins")
        return 0.0, 0.0, 0, 0
    
    # Set up bin ranges
    i_start = j_start = k_start = 1
    i_end = nbinx1
    j_end = nbiny1
    k_end = nbinz1
    
    # Check for axis ranges
    if xaxis1.TestBit(ROOT.TAxis.kAxisRange):
        i_start = xaxis1.GetFirst()
        i_end = xaxis1.GetLast()
    
    if yaxis1.TestBit(ROOT.TAxis.kAxisRange):
        j_start = yaxis1.GetFirst()
        j_end = yaxis1.GetLast()
    
    if zaxis1.TestBit(ROOT.TAxis.kAxisRange):
        k_start = zaxis1.GetFirst()
        k_end = zaxis1.GetLast()
    
    # Handle overflow/underflow options
    opt = option.upper()
    if "OF" in opt:
        if h1.GetDimension() == 3:
            k_end = nbinz1 + 1
        if h1.GetDimension() >= 2:
            j_end = nbiny1 + 1
        if h1.GetDimension() >= 1:
            i_end = nbinx1 + 1
    
    if "UF" in opt:
        if h1.GetDimension() == 3:
            k_start = 0
        if h1.GetDimension() >= 2:
            j_start = 0
        if h1.GetDimension() >= 1:
            i_start = 0
    
    # Calculate degrees of freedom
    ndf = (i_end - i_start + 1) * (j_end - j_start + 1) * (k_end - k_start + 1) - 1
    
    # Determine comparison type
    comparison_uu = "UU" in opt
    comparison_uw = "UW" in opt
    comparison_ww = "WW" in opt
    
    if not (comparison_uu or comparison_uw or comparison_ww):
        comparison_uu = True  # Default is UU
    
    # Calculate sums for normalization
    sum1 = sum2 = 0.0
    sumw1 = sumw2 = 0.0
    
    for i in range(i_start, i_end + 1):
        for j in range(j_start, j_end + 1):
            for k in range(k_start, k_end + 1):
                bin_idx = h1.GetBin(i, j, k)
                sum1 += h1.GetBinContent(bin_idx)
                sum2 += h2.GetBinContent(bin_idx)
                
                if h1.GetSumw2N() > 0:
                    sumw1 += h1.GetBinError(bin_idx) ** 2 - 1
                if h2.GetSumw2N() > 0:
                    sumw2 += h2.GetBinError(bin_idx) ** 2
    
    # Check if histograms are empty
    if sum1 == 0 or sum2 == 0:
        print("Error: One of the histograms is empty")
        return 0.0, 0.0, 0, 0
    
    # Unweighted-unweighted comparison
    if comparison_uu:
        m = n = 0  # Counters for bins with issues
        
        for i in range(i_start, i_end + 1):
            for j in range(j_start, j_end + 1):
                for k in range(k_start, k_end + 1):
                    bin_idx = h1.GetBin(i, j, k)
                    cnt1 = h1.GetBinContent(bin_idx)
                    cnt2 = h2.GetBinContent(bin_idx)
                    
                    # Skip empty bins
                    if cnt1 == 0 and cnt2 == 0:
                        ndf -= 1
                        continue
                    
                    # Check for bins with less than 1 event
                    if cnt1 < 1:
                        m += 1
                    if cnt2 < 1:
                        n += 1
                    
                    # Calculate expected values
                    sum_tot = sum1 + sum2
                    expected1 = sum1 * (cnt1 + cnt2) / sum_tot
                    expected2 = sum2 * (cnt1 + cnt2) / sum_tot
                    
                    # Calculate chi2 contribution
                    if expected1 > 0:
                        chi2 += (cnt1 - expected1) ** 2 / expected1
                    if expected2 > 0:
                        chi2 += (cnt2 - expected2) ** 2 / expected2
        
        # Set igood based on bin issues
        if m > 0:
            igood += 1
        if n > 0:
            igood += 2
    
    # Unweighted-weighted comparison
    elif comparison_uw:
        m = n = 0  # Counters for bins with issues
        
        for i in range(i_start, i_end + 1):
            for j in range(j_start, j_end + 1):
                for k in range(k_start, k_end + 1):
                    bin_idx = h1.GetBin(i, j, k)
                    cnt1 = h1.GetBinContent(bin_idx)
                    cnt2 = h2.GetBinContent(bin_idx)
                    e2sq = h2.GetBinError(bin_idx) ** 2
                    
                    # Skip empty bins
                    if cnt1 == 0 and cnt2 == 0:
                        ndf -= 1
                        continue
                    
                    # Handle case where weighted histogram has zero bin content and error
                    if cnt2 == 0 and e2sq == 0:
                        if sumw2 > 0:
                            e2sq = sumw2 / sum2
                        else:
                            print(f"Error: Hist2 has in bin ({i},{j},{k}) zero content and zero errors")
                            return 0.0, 0.0, 0, 0
                    
                    # Check for bins with issues
                    if cnt1 < 1:
                        m += 1
                    if e2sq > 0 and cnt2 ** 2 / e2sq < 10:
                        n += 1
                    
                    # Calculate variables for chi2
                    var1 = sum2 * cnt2 - sum1 * e2sq
                    var2 = var1 ** 2 + 4.0 * sum2 ** 2 * cnt1 * e2sq
                    
                    # Handle numerical issues
                    while var1 ** 2 + cnt1 == 0 or var1 + numpy.sqrt(var2) == 0:
                        sum1 += 1
                        cnt1 += 1
                        var1 = sum2 * cnt2 - sum1 * e2sq
                        var2 = var1 ** 2 + 4.0 * sum2 ** 2 * cnt1 * e2sq
                    
                    var2 = numpy.sqrt(var2)
                    
                    # Calculate probability and expected values
                    probb = (var1 + var2) / (2.0 * sum2 ** 2)
                    nexp1 = probb * sum1
                    nexp2 = probb * sum2
                    
                    # Calculate deltas and chi2 contribution
                    delta1 = cnt1 - nexp1
                    delta2 = cnt2 - nexp2
                    
                    chi2 += delta1 ** 2 / nexp1
                    if e2sq > 0:
                        chi2 += delta2 ** 2 / e2sq
        
        # Set igood based on bin issues
        if m > 0:
            igood += 1
        if n > 0:
            igood += 2
    
    # Weighted-weighted comparison
    elif comparison_ww:
        m = n = 0  # Counters for bins with issues
        
        for i in range(i_start, i_end + 1):
            for j in range(j_start, j_end + 1):
                for k in range(k_start, k_end + 1):
                    bin_idx = h1.GetBin(i, j, k)
                    cnt1 = h1.GetBinContent(bin_idx)
                    cnt2 = h2.GetBinContent(bin_idx)
                    e1sq = h1.GetBinError(bin_idx) ** 2
                    e2sq = h2.GetBinError(bin_idx) ** 2
                    
                    # Skip empty bins
                    if cnt1 == 0 and cnt2 == 0:
                        ndf -= 1
                        continue
                    
                    # Handle case where histograms have zero bin content and error
                    if cnt1 == 0 and e1sq == 0:
                        if sumw1 > 0:
                            e1sq = sumw1 / sum1
                        else:
                            print(f"Error: Hist1 has in bin ({i},{j},{k}) zero content and zero errors")
                            return 0.0, 0.0, 0, 0
                    
                    if cnt2 == 0 and e2sq == 0:
                        if sumw2 > 0:
                            e2sq = sumw2 / sum2
                        else:
                            print(f"Error: Hist2 has in bin ({i},{j},{k}) zero content and zero errors")
                            return 0.0, 0.0, 0, 0
                    
                    # Check for bins with issues
                    if e1sq > 0 and cnt1 ** 2 / e1sq < 10:
                        m += 1
                    if e2sq > 0 and cnt2 ** 2 / e2sq < 10:
                        n += 1
                    
                    # Calculate chi2 contribution
                    if "NORM" in opt:
                        # Normalized comparison
                        s1 = cnt1 / sum1
                        s2 = cnt2 / sum2
                        es1 = e1sq / (sum1 ** 2)
                        es2 = e2sq / (sum2 ** 2)
                        
                        if es1 + es2 > 0:
                            chi2 += (s1 - s2) ** 2 / (es1 + es2)
                    else:
                        # Direct comparison
                        if e1sq + e2sq > 0:
                            chi2 += (cnt1 - cnt2) ** 2 / (e1sq + e2sq)
        
        # Set igood based on bin issues
        if m > 0:
            igood += 1
        if n > 0:
            igood += 2
    
    # Calculate p-value
    prob = ROOT.TMath.Prob(chi2, ndf)
    
    return prob, chi2, ndf, igood


chi2result = collections.namedtuple("chi2result", ["prob", "chi2", "ndf", "igood"])

def chi2TestX(h1, h2, option="UU"):
    root_chi2 = ctypes.c_double(0)
    root_ndf = ctypes.c_int(0)
    root_igood = ctypes.c_int(0)
    res = ctypes.POINTER(ctypes.c_double)()
    root_prob = h1.Chi2TestX(h2, root_chi2, root_ndf, root_igood, option, res)
    return chi2result(root_prob, root_chi2.value, root_ndf.value, root_igood.value)

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

        int_a, err_a = integralAndError(self.item_a)
        int_b, err_b = integralAndError(self.item_b)
        values = numpy.array([int_a, int_b, err_a, err_b])
        if numpy.any(numpy.isnan(values)) or numpy.any(values == 0):
            return False

        if self.score == 0.0:
            return False

        return True

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
        with push_root_level(ROOT.kWarning):
            res = chi2TestX(self.item_a, self.item_b, "UUOFUF")
            return res

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

        if numpy.isnan(res.chi2):
            return False

        if res.prob == 0.0 or numpy.isnan(res.prob):
            return False

        if res.igood != 0:
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
                self.err_a**2 + self.err_b**2
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
        err = numpy.sqrt(err_a**2 + err_b**2)
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
