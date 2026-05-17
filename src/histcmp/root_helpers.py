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


def get_bin_content(item) -> numpy.array:
    if isinstance(item, ROOT.TH3):
        out = numpy.zeros(
            (
                item.GetXaxis().GetNbins(),
                item.GetYaxis().GetNbins(),
                item.GetZaxis().GetNbins(),
            )
        )

        for i in range(out.shape[0]):
            for j in range(out.shape[1]):
                for k in range(out.shape[2]):
                    out[i][j][k] = item.GetBinContent(i, j, k)

        return out
    elif isinstance(item, ROOT.TH2):
        out = numpy.zeros((item.GetXaxis().GetNbins(), item.GetYaxis().GetNbins()))

        for i in range(out.shape[0]):
            for j in range(out.shape[1]):
                out[i][j] = item.GetBinContent(i, j)

        return out
    elif isinstance(item, ROOT.TH1):
        return numpy.array(
            [item.GetBinContent(b) for b in range(1, item.GetXaxis().GetNbins())]
        )
    else:
        raise TypeError("Invalid type")


# Histogram classes whose underlying fArray buffer is the bin content directly
# and whose errors come from fSumw2 (or sqrt(|content|) when Sumw2 is empty).
# TProfile / TEfficiency override GetBinContent / GetBinError, so they must
# stay on the per-bin fallback path.
_BASIC_TH_DTYPES = {
    "TH1D": numpy.float64, "TH2D": numpy.float64, "TH3D": numpy.float64,
    "TH1F": numpy.float32, "TH2F": numpy.float32, "TH3F": numpy.float32,
    "TH1I": numpy.int32,   "TH2I": numpy.int32,   "TH3I": numpy.int32,
    "TH1S": numpy.int16,   "TH2S": numpy.int16,   "TH3S": numpy.int16,
    "TH1C": numpy.int8,    "TH2C": numpy.int8,    "TH3C": numpy.int8,
    "TH1L": numpy.int64,   "TH2L": numpy.int64,   "TH3L": numpy.int64,
}


def _buffer_to_numpy(buf, n, dtype):
    """Materialize a cppyy pointer buffer of length n into a writable float64 array."""
    try:
        buf.reshape((n,))
    except (AttributeError, TypeError):
        pass
    return numpy.frombuffer(buf, dtype=dtype, count=n).astype(numpy.float64, copy=True)


def _full_content_error(item):
    """Vectorized extraction of full (with under/overflow) content + error arrays.

    Returns (content, error) flat float64 arrays of length item.GetNcells(),
    or (None, None) if the histogram subclass overrides GetBinContent/Error
    (e.g. TProfile, TEfficiency) and a per-bin fallback is required.
    """
    cls = item.ClassName() if hasattr(item, "ClassName") else type(item).__name__
    dtype = _BASIC_TH_DTYPES.get(cls)
    if dtype is None:
        return None, None

    n = item.GetNcells()
    try:
        content = _buffer_to_numpy(item.GetArray(), n, dtype)
    except (TypeError, ValueError):
        return None, None

    sumw2 = item.GetSumw2()
    if sumw2.GetSize() == n:
        try:
            variance = _buffer_to_numpy(sumw2.GetArray(), n, numpy.float64)
        except (TypeError, ValueError):
            return None, None
        error = numpy.sqrt(variance)
    else:
        error = numpy.sqrt(numpy.abs(content))

    return content, error


def is_unweighted_histogram(item) -> bool:
    """Return True iff item was filled without per-entry weights.

    The check mirrors ROOT's own heuristic: a histogram is unweighted when
    its Sumw2 array is empty, or when fSumw2[bin] == |fArray[bin]| for every
    cell (which is what Fill() without a weight produces). Subclasses with
    custom error semantics (TProfile, TEfficiency, ...) are conservatively
    reported as weighted so callers pick the WW-style statistics.
    """
    sumw2 = item.GetSumw2()
    n = item.GetNcells()
    if sumw2.GetSize() != n:
        return True

    cls = item.ClassName() if hasattr(item, "ClassName") else type(item).__name__
    dtype = _BASIC_TH_DTYPES.get(cls)
    if dtype is None:
        return False
    try:
        content = _buffer_to_numpy(item.GetArray(), n, dtype)
        variance = _buffer_to_numpy(sumw2.GetArray(), n, numpy.float64)
    except (TypeError, ValueError):
        return False
    return bool(numpy.array_equal(variance, numpy.abs(content)))


def get_bin_content_error(item) -> numpy.array:
    if isinstance(item, ROOT.TH3):
        nx = item.GetXaxis().GetNbins()
        ny = item.GetYaxis().GetNbins()
        nz = item.GetZaxis().GetNbins()

        content_full, error_full = _full_content_error(item)
        if content_full is not None:
            # ROOT TH3 storage order: bin = (nx+2) * ((ny+2)*k + j) + i
            shape = (nz + 2, ny + 2, nx + 2)
            content = content_full.reshape(shape)[1 : nz + 1, 1 : ny + 1, 1 : nx + 1]
            error = error_full.reshape(shape)[1 : nz + 1, 1 : ny + 1, 1 : nx + 1]
            # Transpose to (nx, ny, nz) to match the historical layout
            return (
                numpy.ascontiguousarray(content.transpose(2, 1, 0)),
                numpy.ascontiguousarray(error.transpose(2, 1, 0)),
            )

        out = numpy.zeros((nx, ny, nz))
        err = numpy.zeros((nx, ny, nz))
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    out[i][j][k] = item.GetBinContent(i + 1, j + 1, k + 1)
                    err[i][j][k] = item.GetBinError(i + 1, j + 1, k + 1)
        return out, err
    elif isinstance(item, ROOT.TH2):
        nx = item.GetXaxis().GetNbins()
        ny = item.GetYaxis().GetNbins()

        content_full, error_full = _full_content_error(item)
        if content_full is not None:
            # ROOT TH2 storage order: bin = (nx+2)*j + i
            shape = (ny + 2, nx + 2)
            content = content_full.reshape(shape)[1 : ny + 1, 1 : nx + 1]
            error = error_full.reshape(shape)[1 : ny + 1, 1 : nx + 1]
            return (
                numpy.ascontiguousarray(content.T),
                numpy.ascontiguousarray(error.T),
            )

        out = numpy.zeros((nx, ny))
        err = numpy.zeros((nx, ny))
        for i in range(nx):
            for j in range(ny):
                out[i][j] = item.GetBinContent(i + 1, j + 1)
                err[i][j] = item.GetBinError(i + 1, j + 1)
        return out, err
    elif isinstance(item, ROOT.TH1):
        nx = item.GetXaxis().GetNbins()

        content_full, error_full = _full_content_error(item)
        if content_full is not None:
            return content_full[1 : nx + 1].copy(), error_full[1 : nx + 1].copy()

        return (
            numpy.array([item.GetBinContent(b) for b in range(1, nx + 1)]),
            numpy.array([item.GetBinError(b) for b in range(1, nx + 1)]),
        )
    else:
        raise TypeError(f"Invalid type {type(item)}")


def _process_axis_title(s):
    def repl(m):
        (o,) = m.groups()
        return "$" + "\\" + o[1:] + "$"

    return re.sub(r"(#[a-zA-Z]+)", repl, s)


def convert_axis(axis):
    if axis.IsVariableBinSize():
        # TAxis stores the (nbins+1) edges in a TArrayD; pull the whole buffer.
        xbins = axis.GetXbins()
        n_edges = xbins.GetSize()
        if n_edges > 0:
            try:
                edges = _buffer_to_numpy(xbins.GetArray(), n_edges, numpy.float64)
            except (TypeError, ValueError):
                edges = numpy.array(
                    [axis.GetBinLowEdge(b) for b in range(1, axis.GetNbins() + 1)]
                    + [axis.GetBinUpEdge(axis.GetNbins())]
                )
        else:
            edges = numpy.array(
                [axis.GetBinLowEdge(b) for b in range(1, axis.GetNbins() + 1)]
                + [axis.GetBinUpEdge(axis.GetNbins())]
            )
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
            label=_process_axis_title(item.GetZaxis().GetTitle()),
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
