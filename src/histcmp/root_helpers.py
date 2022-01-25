from typing import Tuple
import ctypes

import numpy
import ROOT


def integralAndError(item) -> Tuple[float, float]:
    if isinstance(item, ROOT.TH2):
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
        raise TypeError("Invalid type")


def get_bin_content(item) -> numpy.array:
    if isinstance(item, ROOT.TH2):
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


def get_bin_content_error(item) -> numpy.array:
    if isinstance(item, ROOT.TH2):
        out = numpy.zeros((item.GetXaxis().GetNbins(), item.GetYaxis().GetNbins()))
        err = numpy.zeros((item.GetXaxis().GetNbins(), item.GetYaxis().GetNbins()))

        for i in range(out.shape[0]):
            for j in range(out.shape[1]):
                out[i][j] = item.GetBinContent(i, j)
                err[i][j] = item.GetBinError(i, j)

        return out, err
    elif isinstance(item, ROOT.TH1):
        return (
            numpy.array(
                [item.GetBinContent(b) for b in range(1, item.GetXaxis().GetNbins())]
            ),
            numpy.array(
                [item.GetBinError(b) for b in range(1, item.GetXaxis().GetNbins())]
            ),
        )
    else:
        raise TypeError(f"Invalid type {type(item)}")
