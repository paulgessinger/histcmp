import io
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import numpy
import pytest
import typer
import hist

import histcmp.cli


def _report_images(output):
    class Images(HTMLParser):
        def __init__(self):
            super().__init__()
            self.sources = []

        def handle_starttag(self, tag, attrs):
            if tag == "img":
                attributes = dict(attrs)
                assert "src" not in attributes
                self.sources.append(attributes["data-src"])

    parser = Images()
    parser.feed(output.read_text())
    assert parser.sources
    assert all(not src.startswith(("data:", "/")) for src in parser.sources)
    paths = [(output.parent / unquote(src)).resolve() for src in parser.sources]
    for path in paths:
        assert path.suffix == ".png"
        assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    return parser.sources, paths


def _fill_objects(rnd, shift: float):
    import ROOT

    th2 = ROOT.TH2F("th2", "th2;x;y", 8, -3, 3, 8, -3, 3)
    tp2 = ROOT.TProfile2D("tp2", "tp2;x;y", 5, -3, 3, 5, -3, 3)
    th3 = ROOT.TH3F("th3", "th3;x;y;z", 5, -3, 3, 5, -3, 3, 5, -3, 3)
    tp3 = ROOT.TProfile3D("tp3", "tp3;x;y;z", 4, -3, 3, 4, -3, 3, 4, -3, 3)
    th1 = ROOT.TH1F("th1", "th1;x", 10, -3, 3)

    for _ in range(5000):
        x = rnd.Gaus(shift, 1)
        y = rnd.Gaus(-shift, 1)
        z = rnd.Gaus(shift, 1)
        w = rnd.Gaus(2 + shift, 0.5)
        th1.Fill(x)
        th2.Fill(x, y)
        tp2.Fill(x, y, w)
        th3.Fill(x, y, z)
        tp3.Fill(x, y, z, w)

    return [th1, th2, tp2, th3, tp3]


@pytest.fixture(scope="module")
def root_files(tmp_path_factory):
    ROOT = pytest.importorskip("ROOT")
    ROOT.gROOT.SetBatch(ROOT.kTRUE)

    tmp_path = tmp_path_factory.mktemp("data")
    paths = {}
    for name, seed, shift in [
        ("nominal", 42, 0.0),
        ("same", 42, 0.0),
        ("shifted", 43, 0.8),
    ]:
        path = tmp_path / f"{name}.root"
        rf = ROOT.TFile.Open(str(path), "RECREATE")
        rnd = ROOT.TRandom3(seed)
        for obj in _fill_objects(rnd, shift):
            obj.Write()
        rf.Close()
        paths[name] = path

    return paths


@pytest.mark.parametrize("renderer_3d", ["scatter", "voxel"])
@pytest.mark.parametrize("jobs", [1, 2])
def test_identical_files_2d3d(root_files, tmp_path, renderer_3d, jobs):
    output = tmp_path / "reports" / "report.html"
    plots = tmp_path / "plot images #1"

    histcmp.cli.main(
        root_files["nominal"],
        root_files["same"],
        output=output,
        plots=plots,
        format="png",
        jobs=jobs,
        renderer_3d=renderer_3d,
    )

    assert output.exists()
    plot_files = sorted(p.name for p in plots.glob("*.png"))
    expected = ["th1.png"] + sorted(
        f"{key}_{panel}.png"
        for key in ["th2", "tp2", "th3", "tp3"]
        # 2D/3D comparison panels default to the pull metric
        for panel in ["monitored", "reference", "pull"]
    )
    assert plot_files == sorted(expected)
    sources, paths = _report_images(output)
    assert all(src.startswith("../plot%20images%20%231/") for src in sources)
    assert sorted(paths) == sorted(plots.glob("*.png"))


@pytest.mark.parametrize("jobs", [1, 2])
@pytest.mark.parametrize("extension", ["yaml", "toml"])
def test_default_plot_directory(root_files, tmp_path, monkeypatch, jobs, extension):
    from test_report import ReportParser

    monkeypatch.chdir(tmp_path)
    output = Path("reports") / "comparison.html"
    config = tmp_path / f"config.{extension}"
    config.write_text(
        'checks:\n  "*":\n    IntegralCheck:\n      threshold: 3\n'
        'report:\n  tags:\n    Example: ["th*"]\n'
        if extension == "yaml" else
        '[checks."*".IntegralCheck]\nthreshold = 3\n'
        '[report.tags]\nExample = ["th*"]\n'
    )
    histcmp.cli.main(
        root_files["nominal"],
        root_files["same"],
        output=output,
        config_path=config,
        jobs=jobs,
        _filter="^th1$",
    )
    sources, paths = _report_images(output)
    assert sources == ["comparison_plots/th1.png"]
    assert paths == [(output.parent / "comparison_plots" / "th1.png").resolve()]
    metadata = json.loads(ReportParser(output.read_text()).metadata)
    assert metadata["items"][0]["tags"] == ["Example"]


def test_comparison_metric_fallback():
    from histcmp.config import PlotConfig

    # explicit 2D/3D metric wins, unset falls back to the global metric
    assert PlotConfig().effective_comparison_2d3d == "pull"
    assert PlotConfig(comparison="residual").effective_comparison_2d3d == "pull"
    assert (
        PlotConfig(comparison="residual", comparison_2d3d=None).effective_comparison_2d3d
        == "residual"
    )


def test_comparison_metric_2d3d_override(root_files, tmp_path):
    output = tmp_path / "report.html"
    plots = tmp_path / "plots"

    histcmp.cli.main(
        root_files["nominal"],
        root_files["same"],
        output=output,
        plots=plots,
        format="png",
        comparison="pull",
        comparison_2d3d="residual",
    )

    assert (plots / "th2_residual.png").exists()
    assert (plots / "th3_residual.png").exists()
    assert not (plots / "th2_pull.png").exists()


@pytest.mark.parametrize(
    "enable_2d,enable_3d,expected_keys",
    [
        (False, True, ["th1", "th3", "tp3"]),
        (True, False, ["th1", "th2", "tp2"]),
        (False, False, ["th1"]),
    ],
)
def test_disable_2d_3d(root_files, tmp_path, enable_2d, enable_3d, expected_keys):
    output = tmp_path / "report.html"
    plots = tmp_path / "plots"

    histcmp.cli.main(
        root_files["nominal"],
        root_files["same"],
        output=output,
        plots=plots,
        format="png",
        enable_2d=enable_2d,
        enable_3d=enable_3d,
    )

    plotted_keys = sorted({p.stem.split("_")[0] for p in plots.glob("*.png")})
    assert plotted_keys == sorted(expected_keys)


def test_shifted_files_fail(root_files, tmp_path):
    with pytest.raises(typer.Exit):
        histcmp.cli.main(
            root_files["nominal"],
            root_files["shifted"],
            output=tmp_path / "report.html",
            plots=tmp_path / "plots",
            format="png",
        )


def _load_pairs(root_files, name_a, name_b):
    import ROOT

    rf_a = ROOT.TFile.Open(str(root_files[name_a]))
    rf_b = ROOT.TFile.Open(str(root_files[name_b]))
    out = {}
    for key in ["th1", "th2", "tp2", "th3", "tp3"]:
        a = rf_a.Get(key)
        b = rf_b.Get(key)
        a.SetDirectory(0)
        b.SetDirectory(0)
        out[key] = (a, b)
    rf_a.Close()
    rf_b.Close()
    return out


@pytest.fixture(scope="module")
def hist_pairs(root_files):
    return {
        "same": _load_pairs(root_files, "nominal", "same"),
        "shifted": _load_pairs(root_files, "nominal", "shifted"),
    }


@pytest.mark.parametrize("key", ["th2", "tp2", "th3", "tp3"])
def test_checks_native_nd(hist_pairs, key):
    pytest.importorskip("ROOT")
    from histcmp.checks import (
        KolmogorovTest,
        Chi2Test,
        RatioCheck,
        ResidualCheck,
        IntegralCheck,
    )

    same = hist_pairs["same"][key]
    shifted = hist_pairs["shifted"][key]

    for ctype in [RatioCheck, ResidualCheck]:
        check = ctype(*same)
        assert check.is_applicable, f"{ctype.__name__} not applicable for {key}"
        assert check.is_valid

        check = ctype(*shifted)
        assert check.is_applicable
        assert not check.is_valid

    if key in ("th2", "th3"):
        for ctype in [KolmogorovTest, Chi2Test, IntegralCheck]:
            check = ctype(*same)
            assert check.is_applicable, f"{ctype.__name__} not applicable for {key}"
            assert check.is_valid

        # shape sensitive tests must catch the shifted distribution
        # (IntegralCheck is excluded: a mean shift barely changes the integral)
        for ctype in [KolmogorovTest, Chi2Test]:
            check = ctype(*shifted)
            if check.is_applicable:
                assert not check.is_valid


@pytest.mark.parametrize("key", ["th1", "th2", "tp2", "th3", "tp3"])
def test_get_bin_content_error_matches_root(hist_pairs, key):
    from histcmp.root_helpers import get_bin_content_error

    item, _ = hist_pairs["same"][key]
    out, err = get_bin_content_error(item)

    for idx in numpy.ndindex(out.shape):
        root_bin = tuple(i + 1 for i in idx)
        assert out[idx] == pytest.approx(item.GetBinContent(*root_bin)), idx
        assert err[idx] == pytest.approx(item.GetBinError(*root_bin)), idx


def test_residual_check_nd_bin_count(hist_pairs):
    pytest.importorskip("ROOT")
    from histcmp.checks import ResidualCheck

    a, b = hist_pairs["same"]["th3"]
    check = ResidualCheck(a, b)
    # regression: len() on an N-D array returned the first axis length instead
    # of the total number of bins
    assert "125" in check.label


def _make_hist(shape, values=None):
    axes = [
        hist.axis.Regular(n, 0, n, name="xyz"[i]) for i, n in enumerate(shape)
    ]
    h = hist.Hist(
        *axes,
        storage=hist.storage.Weight(),
        name=f"test {len(shape)}d",
        label="entries",
    )
    if values is not None:
        h.view().value = values
        h.view().variance = numpy.abs(values)
    return h


@pytest.mark.parametrize(
    "plotter",
    ["plot_2d", "plot_3d_scatter", "plot_3d_voxel"],
)
@pytest.mark.parametrize(
    "case", ["identical", "different", "partially_empty", "empty"]
)
def test_plot_functions(plotter, case):
    from histcmp import plot
    from matplotlib import pyplot

    shape = (4, 4) if plotter == "plot_2d" else (3, 3, 3)

    rng = numpy.random.default_rng(1234)
    values = rng.uniform(1, 100, size=shape)

    if case == "identical":
        va, vb = values, values.copy()
    elif case == "different":
        va, vb = values, values * rng.uniform(0.5, 1.5, size=shape)
    elif case == "partially_empty":
        va = values.copy()
        vb = values.copy()
        va[..., 0] = 0
        vb[..., -1] = 0
    else:
        va = numpy.zeros(shape)
        vb = numpy.zeros(shape)

    a = _make_hist(shape, va)
    b = _make_hist(shape, vb)

    figs = getattr(plot, plotter)(a, b, "monitored", "reference")
    assert [suffix for suffix, _ in figs] == ["_monitored", "_reference", "_ratio"]

    for _, fig in figs:
        image = io.BytesIO()
        fig.savefig(image, format="png", dpi=120)
        assert image.getvalue().startswith(b"\x89PNG\r\n\x1a\n")

        pyplot.close(fig)


@pytest.mark.parametrize(
    "plotter", ["plot_2d", "plot_3d_scatter", "plot_3d_voxel"]
)
@pytest.mark.parametrize("comparison", ["ratio", "residual", "pull", "asymmetry"])
def test_plot_comparison_metrics(plotter, comparison):
    from histcmp import plot
    from matplotlib import pyplot

    shape = (4, 4) if plotter == "plot_2d" else (3, 3, 3)

    rng = numpy.random.default_rng(1234)
    va = rng.uniform(1, 100, size=shape)
    vb = va * rng.uniform(0.5, 1.5, size=shape)

    figs = getattr(plot, plotter)(
        _make_hist(shape, va), _make_hist(shape, vb), "a", "b", comparison
    )
    assert [suffix for suffix, _ in figs] == [
        "_monitored",
        "_reference",
        f"_{comparison}",
    ]

    for _, fig in figs:
        pyplot.close(fig)


@pytest.mark.parametrize("comparison", ["ratio", "residual", "pull", "asymmetry"])
def test_plot_1d_comparison_metrics(comparison):
    from histcmp import plot
    from matplotlib import pyplot

    rng = numpy.random.default_rng(1234)
    va = rng.uniform(1, 100, size=10)
    vb = va * rng.uniform(0.8, 1.2, size=10)
    a = _make_hist((10,), va)
    b = _make_hist((10,), vb)

    fig, (ax, rax) = plot.plot_1d(a, b, "monitored", "reference", comparison)
    image = io.BytesIO()
    fig.savefig(image, format="png", dpi=120)
    assert image.getvalue().startswith(b"\x89PNG\r\n\x1a\n")

    pyplot.close(fig)


@pytest.mark.parametrize("kind,shape", [("1d", (4,)), ("2d", (4, 4)), ("3d", (3, 3, 3))])
def test_report_renders_each_plot_once(tmp_path, monkeypatch, kind, shape):
    from matplotlib.figure import Figure
    from histcmp.compare import Comparison, ComparisonItem
    from histcmp.plot import PlotSpec
    from histcmp.report import make_report

    histogram = _make_hist(shape, numpy.ones(shape))
    spec = PlotSpec(kind, histogram, histogram.copy(), renderer="scatter")
    item = ComparisonItem("directory/hist #1", None, None)
    monkeypatch.setattr(item, "plot_specs", lambda: [spec])
    comparison = Comparison(
        "a.root", "b.root", label_monitored="a", label_reference="b", items=[item]
    )
    saved = []
    savefig = Figure.savefig

    def record_save(figure, path, *args, **kwargs):
        saved.append(path)
        return savefig(figure, path, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", record_save)
    output = tmp_path / "report.html"
    make_report(comparison, output)
    _, paths = _report_images(output)
    assert len(paths) == (1 if kind == "1d" else 3)
    assert saved == paths
    assert item.generic_plots == paths

    # Reassembling HTML must reuse the files, including when the report moves.
    moved_output = tmp_path / "nested" / "report.html"
    make_report(comparison, moved_output)
    _, moved_paths = _report_images(moved_output)
    assert moved_paths == paths
    assert saved == paths


def test_voxel_fallback_to_scatter(capsys):
    from histcmp import plot

    h = _make_hist((30, 30, 30), numpy.ones((30, 30, 30)))

    figs = plot.plot_3d_voxel(h, h.copy(), "a", "b")
    assert len(figs) == 3
    assert "falling back" in capsys.readouterr().out

    from matplotlib import pyplot

    for _, fig in figs:
        pyplot.close(fig)
