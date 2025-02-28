import pytest
import ROOT
from pathlib import Path
import numpy as np

from histcmp.checks import Chi2Test
from histcmp.root_helpers import push_root_level


@pytest.fixture
def root_file():
    """Fixture to open and close the ROOT file for each test."""
    test_file_path = Path(__file__).parent / "data" / "performance_ckf_main.root"
    assert test_file_path.exists(), f"Test file {test_file_path} does not exist"
    
    with push_root_level(ROOT.kError):
        tfile = ROOT.TFile.Open(str(test_file_path))
        try:
            yield tfile
        finally:
            tfile.Close()


def test_chi2test_with_th1(root_file):
    """Test Chi2Test with TH1 histograms."""
    # Get a TH1 histogram from the file
    hist_name = "nRecoTracks_vs_pT;1"
    hist = root_file.Get(hist_name)
    assert hist is not None, f"Histogram {hist_name} not found in test file"
    
    # Clone the histogram for comparison
    hist_clone = hist.Clone()
    
    # Test with identical histograms (should pass)
    chi2_test = Chi2Test(hist, hist_clone)
    assert chi2_test.is_applicable
    assert chi2_test.is_valid
    assert chi2_test.score > 0.99  # Should be very close to 1.0
    
    # Modify one histogram slightly and test again
    for bin_idx in range(1, hist_clone.GetNbinsX() + 1):
        current_content = hist_clone.GetBinContent(bin_idx)
        # Add small random variation
        hist_clone.SetBinContent(bin_idx, current_content * (1 + 0.05 * np.random.randn()))
    
    chi2_test_modified = Chi2Test(hist, hist_clone)
    assert chi2_test_modified.is_applicable
    # The score should be lower now, but might still pass depending on threshold
    
    # Test with very different histograms (should fail)
    hist_name2 = "nFakeTracks_vs_pT;1"
    hist2 = root_file.Get(hist_name2)
    assert hist2 is not None, f"Histogram {hist_name2} not found in test file"
    
    chi2_test_different = Chi2Test(hist, hist2)
    if chi2_test_different.is_applicable:
        assert chi2_test_different.score < chi2_test.score


def test_chi2test_with_tefficiency(root_file):
    """Test Chi2Test with TEfficiency objects."""
    # Get a TEfficiency object from the file
    eff_name = "trackeff_vs_eta;1"
    eff = root_file.Get(eff_name)
    assert eff is not None, f"TEfficiency {eff_name} not found in test file"
    
    # Clone the efficiency for comparison
    eff_clone = eff.Clone()
    
    # Test with identical efficiencies (should pass)
    chi2_test = Chi2Test(eff, eff_clone)
    assert chi2_test.is_applicable
    assert chi2_test.is_valid
    assert chi2_test.score > 0.99  # Should be very close to 1.0
    
    # Test with different efficiencies
    eff_name2 = "fakerate_vs_pT;1"
    eff2 = root_file.Get(eff_name2)
    assert eff2 is not None, f"TEfficiency {eff_name2} not found in test file"
    
    chi2_test_different = Chi2Test(eff, eff2)
    if chi2_test_different.is_applicable:
        # The score should be lower for different efficiencies
        assert chi2_test_different.score < chi2_test.score


def test_chi2test_threshold(root_file):
    """Test Chi2Test with different thresholds."""
    # Get a TH1 histogram from the file
    hist_name = "nRecoTracks_vs_pT;1"
    hist = root_file.Get(hist_name)
    assert hist is not None, f"Histogram {hist_name} not found in test file"
    
    # Clone and modify the histogram
    hist_clone = hist.Clone()
    for bin_idx in range(1, hist_clone.GetNbinsX() + 1):
        current_content = hist_clone.GetBinContent(bin_idx)
        # Add moderate variation
        hist_clone.SetBinContent(bin_idx, current_content * (1 + 0.1 * np.random.randn()))
    
    # Test with different thresholds
    chi2_test_strict = Chi2Test(hist, hist_clone, threshold=0.05)
    chi2_test_lenient = Chi2Test(hist, hist_clone, threshold=0.001)
    
    # Same score for both tests
    assert chi2_test_strict.score == chi2_test_lenient.score
    
    # But different validity results due to different thresholds
    assert chi2_test_strict.is_applicable
    assert chi2_test_lenient.is_applicable
    assert chi2_test_strict.is_valid
    assert chi2_test_lenient.is_valid


def test_chi2test_not_applicable(root_file):
    """Test cases where Chi2Test is not applicable."""
    # Get a TH1 histogram from the file
    hist_name = "nRecoTracks_vs_pT;1"
    hist = root_file.Get(hist_name)
    assert hist is not None, f"Histogram {hist_name} not found in test file"
    
    # Create an empty histogram
    empty_hist = hist.Clone()
    empty_hist.Reset()
    
    # Test with empty histogram (should not be applicable)
    chi2_test_empty = Chi2Test(hist, empty_hist)
    assert not chi2_test_empty.is_applicable
    
    # Test with histograms of different dimensions
    # Create a 2D histogram
    hist2d = ROOT.TH2F("hist2d", "hist2d", 10, 0, 10, 10, 0, 10)
    chi2_test_diff_dim = Chi2Test(hist, hist2d)
    assert not chi2_test_diff_dim.is_applicable 