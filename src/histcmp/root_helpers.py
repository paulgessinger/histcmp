from typing import Tuple
import ctypes
import contextlib
import hist
import hist.intervals
import re

import numpy
import ROOT

ROOT.gStyle.SetOptStat(0)


@contextlib.contextmanager
def push_root_level(value):
    prev = ROOT.gErrorIgnoreLevel
    ROOT.gErrorIgnoreLevel = value
    try:
        yield
    finally:
        ROOT.gErrorIgnoreLevel = prev


def integralAndError(item) -> Tuple[float, float]:
    if isinstance(item, ROOT.TH3):
        e = ctypes.c_double(-1)
        i = item.IntegralAndError(
            0,
            item.GetXaxis().GetNbins(),
            0,
            item.GetYaxis().GetNbins(),
            0,
            item.GetZaxis().GetNbins(),
            e,
        )
        return i, e.value
    elif isinstance(item, ROOT.TH2):
        e = ctypes.c_double(-1)
        i = item.IntegralAndError(
            0, item.GetXaxis().GetNbins(), 0, item.GetYaxis().GetNbins(), e
        )
        return i, e.value
    elif isinstance(item, ROOT.TH1):
        e = ctypes.c_double(-1)
        i = item.IntegralAndError(0, item.GetXaxis().GetNbins(), e)
        return i, e.value
    else:
        raise TypeError(f"Invalid type {type(item)}")


def _bin_shape(item):
    if isinstance(item, ROOT.TH3):
        return (item.GetNbinsX(), item.GetNbinsY(), item.GetNbinsZ())
    elif isinstance(item, ROOT.TH2):
        return (item.GetNbinsX(), item.GetNbinsY())
    elif isinstance(item, ROOT.TH1):
        return (item.GetNbinsX(),)
    else:
        raise TypeError(f"Invalid type {type(item)}")


def _get_bin_content_error_loop(item) -> Tuple[numpy.ndarray, numpy.ndarray]:
    shape = _bin_shape(item)
    out = numpy.zeros(shape)
    err = numpy.zeros(shape)

    for idx in numpy.ndindex(shape):
        root_bin = tuple(i + 1 for i in idx)
        out[idx] = item.GetBinContent(*root_bin)
        err[idx] = item.GetBinError(*root_bin)

    return out, err


def get_bin_content_error(item) -> Tuple[numpy.ndarray, numpy.ndarray]:
    """
    Bin contents and errors as N-D numpy arrays, without under/overflow bins.
    """
    if isinstance(item, (ROOT.TProfile, ROOT.TProfile2D, ROOT.TProfile3D)):
        # for profiles the raw buffer holds weighted sums, not the profiled
        # means that GetBinContent returns, so go through the per-bin API
        return _get_bin_content_error_loop(item)

    shape = _bin_shape(item)
    # the flat buffer includes under/overflow bins and runs fastest along x:
    # global bin = x + (nx+2) * (y + (ny+2) * z)
    buf_shape = tuple(n + 2 for n in reversed(shape))

    arr = item.GetArray()
    arr.reshape((item.GetSize(),))
    core = tuple(slice(1, -1) for _ in shape)
    out = numpy.array(arr, dtype=numpy.float64).reshape(buf_shape).T[core]

    sumw2 = item.GetSumw2()
    if sumw2.GetSize() > 0:
        w2 = sumw2.GetArray()
        w2.reshape((sumw2.GetSize(),))
        err = numpy.sqrt(
            numpy.array(w2, dtype=numpy.float64).reshape(buf_shape).T[core]
        )
    else:
        err = numpy.sqrt(numpy.abs(out))

    return out, err


def _process_axis_title(s):
    def repl(m):
        (o,) = m.groups()
        return "$" + "\\" + o[1:] + "$"

    return re.sub(r"(#[a-zA-Z]+)", repl, s)


def convert_axis(axis):
    if axis.IsVariableBinSize():
        #  print("variable")
        edges = [axis.GetBinLowEdge(b) for b in range(1, axis.GetNbins() + 1)]
        edges.append(axis.GetBinUpEdge(axis.GetNbins()))
        axis = hist.axis.Variable(edges, name=_process_axis_title(axis.GetTitle()))
        return axis
    else:
        #  print(axis.GetNbins())
        ax = hist.axis.Regular(
            axis.GetNbins(),
            axis.GetBinLowEdge(1),
            axis.GetBinUpEdge(axis.GetNbins()),
            name=_process_axis_title(axis.GetTitle()),
        )
        #  print(ax)
        return ax


def convert_hist(item):
    if isinstance(item, ROOT.TH3):
        h = hist.Hist(
            convert_axis(item.GetXaxis()),
            convert_axis(item.GetYaxis()),
            convert_axis(item.GetZaxis()),
            storage=hist.storage.Weight(),
            name=_process_axis_title(item.GetTitle()),
            # for a TH3 the z axis is a real axis, there is no title for the
            # bin content axis
            label="",
        )
        cont, err = get_bin_content_error(item)
        h.view().value = cont
        h.view().variance = err ** 2
        return h
    elif isinstance(item, ROOT.TH2):
        h = hist.Hist(
            convert_axis(item.GetXaxis()),
            convert_axis(item.GetYaxis()),
            storage=hist.storage.Weight(),
            name=_process_axis_title(item.GetTitle()),
            label=_process_axis_title(item.GetZaxis().GetTitle()),
        )
        cont, err = get_bin_content_error(item)
        h.view().value = cont
        h.view().variance = err ** 2
        return h
    elif isinstance(item, ROOT.TEfficiency):
        passed = convert_hist(item.GetPassedHistogram())
        #  total = convert_hist(item.GetTotalHistogram())

        eff = passed[:]
        eff.reset()
        eff.name = _process_axis_title(item.GetTitle())

        nbins = item.GetPassedHistogram().GetNbinsX()
        values = numpy.zeros(nbins)
        error = numpy.zeros((2, nbins))
        for b in range(1, nbins + 1):
            values[b - 1] = item.GetEfficiency(b)
            #  error[b - 1] = 0.5 * (
            #  item.GetEfficiencyErrorUp(b) + item.GetEfficiencyErrorLow(b)
            #  )

            if values[b - 1] != 0:
                error[1][b - 1] = item.GetEfficiencyErrorUp(b)
                error[0][b - 1] = item.GetEfficiencyErrorLow(b)

        #  print(values)
        #  print(error)
        eff.view().value = values
        eff.view().variance = ((error[0] + error[1]) / 2) ** 2

        #  print(eff.name)
        #  print(values)
        #  print(error)

        #  eff.view().value = passed.view().value / total.view().value
        #  lo, hi = hist.intervals.clopper_pearson_interval(
        #  passed.view().value, total.view().value
        #  )
        #  #  print("vl", eff.view().value)
        #  #  print("lo", lo)
        #  #  print("hi", hi)
        #  v = eff.view().value
        #  lo = v - lo
        #  hi = hi - v
        #  eff.view().variance = (lo + hi) / 2.0 ** 2  # - eff.view().value  # ** 2

        return eff, error

    elif isinstance(item, ROOT.TH1):
        h = hist.Hist(
            convert_axis(item.GetXaxis()),
            storage=hist.storage.Weight(),
            name=_process_axis_title(item.GetTitle()),
            label=_process_axis_title(item.GetYaxis().GetTitle()),
        )
        cont, err = get_bin_content_error(item)
        h.view().value = cont
        h.view().variance = err ** 2
        return h


def tefficiency_to_th1(eff):
    out = eff.GetPassedHistogram().Clone()
    out.SetDirectory(0)
    out.Reset()

    for b in range(1, out.GetXaxis().GetNbins()):
        out.SetBinContent(b, eff.GetEfficiency(b))
        err = 0.5 * (eff.GetEfficiencyErrorLow(b) + eff.GetEfficiencyErrorUp(b))
        out.SetBinError(b, err)

    return out
