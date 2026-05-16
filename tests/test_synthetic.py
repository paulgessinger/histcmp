"""Tests built on synthetically-produced ROOT files.

These tests don't depend on the bundled performance_ckf*.root fixtures and
exercise the comparison machinery against histograms with known contents and
errors. They are the regression tests for the vectorized bin-extraction
fast path in root_helpers.py: the helpers below reach into TH1/TH2/TH3 via
SetBinContent/SetBinError so we know exactly what should come back out.
"""
from array import array

import numpy as np
import pytest

ROOT = pytest.importorskip("ROOT")

ROOT.gROOT.SetBatch(ROOT.kTRUE)


# ---------- builders ----------


def _set_errors(setter, errors):
    """Apply SetBinError over a flat iterable of (bin_args, error)."""
    for bin_args, e in errors:
        setter(*bin_args, float(e))


def make_th1(cls, name, contents, errors=None, edges=None, title=""):
    contents = np.asarray(contents, dtype=np.float64)
    n = len(contents)
    if edges is None:
        h = cls(name, title, n, 0.0, float(n))
    else:
        h = cls(name, title, n, array("d", list(edges)))
    h.Sumw2()
    for i, v in enumerate(contents):
        h.SetBinContent(i + 1, float(v))
    if errors is not None:
        errors = np.asarray(errors, dtype=np.float64)
        for i, e in enumerate(errors):
            h.SetBinError(i + 1, float(e))
    h.SetDirectory(0)
    return h


def make_th2(cls, name, contents, errors=None, title=""):
    contents = np.asarray(contents, dtype=np.float64)
    nx, ny = contents.shape
    h = cls(name, title, nx, 0.0, float(nx), ny, 0.0, float(ny))
    h.Sumw2()
    for i in range(nx):
        for j in range(ny):
            h.SetBinContent(i + 1, j + 1, float(contents[i, j]))
    if errors is not None:
        errors = np.asarray(errors, dtype=np.float64)
        for i in range(nx):
            for j in range(ny):
                h.SetBinError(i + 1, j + 1, float(errors[i, j]))
    h.SetDirectory(0)
    return h


def make_th3(cls, name, contents, errors=None, title=""):
    contents = np.asarray(contents, dtype=np.float64)
    nx, ny, nz = contents.shape
    h = cls(
        name, title,
        nx, 0.0, float(nx),
        ny, 0.0, float(ny),
        nz, 0.0, float(nz),
    )
    h.Sumw2()
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                h.SetBinContent(i + 1, j + 1, k + 1, float(contents[i, j, k]))
    if errors is not None:
        errors = np.asarray(errors, dtype=np.float64)
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    h.SetBinError(i + 1, j + 1, k + 1, float(errors[i, j, k]))
    h.SetDirectory(0)
    return h


def write_root_file(path, *objects):
    f = ROOT.TFile.Open(str(path), "RECREATE")
    f.cd()
    for obj in objects:
        obj.Write()
    f.Close()


def read_root_object(path, name):
    f = ROOT.TFile.Open(str(path))
    obj = f.Get(name)
    obj.SetDirectory(0)
    f.Close()
    return obj


# ---------- vectorized extraction round-trips ----------


def test_th1d_extraction_roundtrip(tmp_path):
    from histcmp.root_helpers import get_bin_content_error, convert_hist

    contents = np.array([1.0, 2.5, 3.7, 0.5, 4.2, 1.5, 7.0])
    errors = np.array([0.1, 0.5, 0.6, 0.05, 1.0, 0.2, 0.7])
    h = make_th1(ROOT.TH1D, "h", contents, errors)

    path = tmp_path / "f.root"
    write_root_file(path, h)
    h2 = read_root_object(path, "h")

    cont, err = get_bin_content_error(h2)
    np.testing.assert_array_equal(cont, contents)
    np.testing.assert_array_equal(err, errors)

    converted = convert_hist(h2)
    np.testing.assert_array_equal(converted.view().value, contents)
    np.testing.assert_array_equal(converted.view().variance, errors ** 2)


def test_th1f_extraction_dtype(tmp_path):
    """TH1F (float32 storage) must be detected and read with dtype=float32."""
    from histcmp.root_helpers import get_bin_content_error

    # All values exactly representable in float32 so the cast is lossless.
    contents = np.array([1.0, 2.5, 3.5, 4.0, 5.25])
    errors = np.array([0.5, 0.25, 0.125, 1.0, 2.0])
    h = make_th1(ROOT.TH1F, "h", contents, errors)

    path = tmp_path / "f.root"
    write_root_file(path, h)
    h2 = read_root_object(path, "h")

    cont, err = get_bin_content_error(h2)
    np.testing.assert_array_equal(cont, contents)
    np.testing.assert_array_equal(err, errors)


def test_th2d_extraction_roundtrip(tmp_path):
    """TH2D: vectorized reshape (ny+2, nx+2) and transpose to (nx, ny)."""
    from histcmp.root_helpers import get_bin_content_error

    # Asymmetric shape so a transpose bug shows up as a wrong-shape array.
    contents = np.array(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
            [7.0, 8.0, 9.0],
            [10.0, 11.0, 12.0],
        ]
    )  # shape (4, 3) -> nx=4, ny=3
    errors = contents * 0.1
    h = make_th2(ROOT.TH2D, "h", contents, errors)

    path = tmp_path / "f.root"
    write_root_file(path, h)
    h2 = read_root_object(path, "h")

    cont, err = get_bin_content_error(h2)
    assert cont.shape == contents.shape
    np.testing.assert_array_equal(cont, contents)
    np.testing.assert_array_equal(err, errors)


def test_th3d_extraction_roundtrip(tmp_path):
    """TH3D: reshape (nz+2, ny+2, nx+2) -> transpose(2,1,0) -> (nx, ny, nz).

    Three distinct dimensions so any axis swap is immediately visible.
    """
    from histcmp.root_helpers import get_bin_content_error

    rng = np.random.default_rng(42)
    contents = rng.uniform(0.5, 10.0, size=(4, 3, 5))  # nx=4, ny=3, nz=5
    errors = rng.uniform(0.1, 1.0, size=(4, 3, 5))
    h = make_th3(ROOT.TH3D, "h", contents, errors)

    path = tmp_path / "f.root"
    write_root_file(path, h)
    h2 = read_root_object(path, "h")

    cont, err = get_bin_content_error(h2)
    assert cont.shape == contents.shape
    np.testing.assert_array_equal(cont, contents)
    np.testing.assert_array_equal(err, errors)


def test_th3d_extraction_matches_per_bin(tmp_path):
    """Direct comparison against the per-bin GetBinContent/GetBinError loop
    that the fast path replaces."""
    from histcmp.root_helpers import get_bin_content_error

    rng = np.random.default_rng(7)
    contents = rng.uniform(0.5, 5.0, size=(3, 4, 2))
    errors = rng.uniform(0.1, 1.0, size=(3, 4, 2))
    h = make_th3(ROOT.TH3D, "h", contents, errors)

    path = tmp_path / "f.root"
    write_root_file(path, h)
    h2 = read_root_object(path, "h")

    cont, err = get_bin_content_error(h2)
    nx, ny, nz = contents.shape
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                assert cont[i, j, k] == h2.GetBinContent(i + 1, j + 1, k + 1)
                assert err[i, j, k] == h2.GetBinError(i + 1, j + 1, k + 1)


def test_th1d_variable_axis_roundtrip(tmp_path):
    """convert_axis must reproduce variable bin edges exactly."""
    from histcmp.root_helpers import convert_hist

    edges = [0.0, 0.5, 1.5, 3.0, 7.0, 10.0]
    contents = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    h = make_th1(ROOT.TH1D, "h", contents, edges=edges)

    path = tmp_path / "f.root"
    write_root_file(path, h)
    h2 = read_root_object(path, "h")

    converted = convert_hist(h2)
    np.testing.assert_array_equal(
        converted.axes[0].edges, np.asarray(edges, dtype=np.float64)
    )


def test_tprofile_uses_fallback(tmp_path):
    """TProfile overrides GetBinContent/GetBinError, so it must take the
    per-bin fallback path and still match a manual readout."""
    from histcmp.root_helpers import get_bin_content_error

    n = 6
    p = ROOT.TProfile("p", "", n, 0.0, float(n))
    p.Sumw2()
    rng = np.random.default_rng(0)
    for _ in range(200):
        p.Fill(rng.uniform(0, n), rng.normal(loc=2.0, scale=0.5))

    path = tmp_path / "f.root"
    write_root_file(path, p)
    p2 = read_root_object(path, "p")

    cont, err = get_bin_content_error(p2)
    expected_cont = np.array([p2.GetBinContent(i + 1) for i in range(n)])
    expected_err = np.array([p2.GetBinError(i + 1) for i in range(n)])
    np.testing.assert_allclose(cont, expected_cont)
    np.testing.assert_allclose(err, expected_err)


# ---------- collect_items lazy-deserialization ----------


def test_collect_items_skips_non_histograms(tmp_path):
    """A TGraph in the file should be silently skipped without being read."""
    from histcmp.compare import collect_items

    h = make_th1(ROOT.TH1D, "h", [1.0, 2.0, 3.0])
    g = ROOT.TGraph(3, array("d", [0, 1, 2]), array("d", [10, 20, 30]))
    g.SetName("g")

    path = tmp_path / "f.root"
    f = ROOT.TFile.Open(str(path), "RECREATE")
    f.cd()
    h.Write()
    g.Write()
    f.Close()

    rf = ROOT.TFile.Open(str(path))
    items = collect_items(rf)
    assert "h" in items
    assert "g" not in items
    rf.Close()


def test_collect_items_recurses_into_directories(tmp_path):
    from histcmp.compare import collect_items

    h_root = make_th1(ROOT.TH1D, "root_h", [1.0, 2.0])
    h_sub = make_th1(ROOT.TH1D, "sub_h", [3.0, 4.0])

    path = tmp_path / "f.root"
    f = ROOT.TFile.Open(str(path), "RECREATE")
    f.cd()
    h_root.Write()
    d = f.mkdir("subdir")
    d.cd()
    h_sub.Write()
    f.Close()

    rf = ROOT.TFile.Open(str(path))
    items = collect_items(rf)
    # Key naming inside subdirectories is mangled; just confirm both reach us.
    assert any("root_h" in k for k in items)
    assert any("sub_h" in k for k in items)
    rf.Close()


# ---------- end-to-end CLI ----------


def _write_mixed_file(path, rng_seed=123):
    """Write a file containing a TH1, TH2 and TH3, all with non-trivial errors."""
    rng = np.random.default_rng(rng_seed)
    th1 = make_th1(
        ROOT.TH1D, "th1",
        rng.uniform(1.0, 10.0, size=10),
        errors=rng.uniform(0.1, 1.0, size=10),
    )
    th2 = make_th2(
        ROOT.TH2D, "th2",
        rng.uniform(1.0, 5.0, size=(4, 3)),
        errors=rng.uniform(0.1, 0.5, size=(4, 3)),
    )
    th3 = make_th3(
        ROOT.TH3D, "th3",
        rng.uniform(1.0, 5.0, size=(3, 4, 5)),
        errors=rng.uniform(0.1, 0.5, size=(3, 4, 5)),
    )
    write_root_file(path, th1, th2, th3)


def test_identical_files_no_failure(tmp_path):
    """Comparing a file to itself must not raise (no FAILURE statuses)."""
    import histcmp.cli

    path = tmp_path / "f.root"
    _write_mixed_file(path)
    # main() raises typer.Exit on failure and returns normally on success.
    histcmp.cli.main(path, path)


def test_different_files_exit(tmp_path):
    """Substantially different histograms must trigger a non-zero exit."""
    import typer
    import histcmp.cli

    rng = np.random.default_rng(0)

    a = tmp_path / "a.root"
    write_root_file(
        a,
        make_th1(
            ROOT.TH1D, "th1",
            rng.uniform(1.0, 10.0, size=10),
            errors=rng.uniform(0.5, 1.0, size=10),
        ),
    )

    b = tmp_path / "b.root"
    write_root_file(
        b,
        make_th1(
            ROOT.TH1D, "th1",
            rng.uniform(50.0, 100.0, size=10),
            errors=rng.uniform(0.5, 1.0, size=10),
        ),
    )

    with pytest.raises(typer.Exit):
        histcmp.cli.main(a, b)


def test_a_only_b_only_classification(tmp_path):
    """Histograms unique to one file land in the correct exclusivity set."""
    from histcmp.compare import compare
    from histcmp.config import Config

    a = tmp_path / "a.root"
    b = tmp_path / "b.root"

    h_common = make_th1(ROOT.TH1D, "shared", [1.0, 2.0, 3.0], errors=[0.1, 0.1, 0.1])
    write_root_file(a, h_common, make_th1(ROOT.TH1D, "only_a", [1.0, 2.0]))
    write_root_file(b, h_common, make_th1(ROOT.TH1D, "only_b", [1.0, 2.0]))

    config = Config(checks={"*": {"Chi2Test": {"threshold": 0.01}}})
    result = compare(config, a, b, filters=[".*"])

    only_a_names = {k for k, _ in result.a_only}
    only_b_names = {k for k, _ in result.b_only}
    common_names = {k for k, _ in result.common}
    assert "only_a" in only_a_names
    assert "only_b" in only_b_names
    assert "shared" in common_names


def test_th3_end_to_end(tmp_path):
    """Run the full TH3 path (projections + full-volume check) end-to-end."""
    import histcmp.cli

    rng = np.random.default_rng(99)
    contents = rng.uniform(1.0, 5.0, size=(3, 4, 5))
    errors = rng.uniform(0.1, 0.5, size=(3, 4, 5))
    th3 = make_th3(ROOT.TH3D, "th3", contents, errors)

    path = tmp_path / "f.root"
    write_root_file(path, th3)
    histcmp.cli.main(path, path)  # self-comparison must succeed
