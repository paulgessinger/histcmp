#!/usr/bin/env python3
import ROOT
import numpy as np
import sys
from pathlib import Path
import ctypes

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from histcmp.checks import chi2_test_x

def create_test_histograms():
    """Create test histograms with different distributions."""
    # Create identical histograms
    h1 = ROOT.TH1F("h1", "Histogram 1", 10, 0, 10)
    h2 = ROOT.TH1F("h2", "Histogram 2", 10, 0, 10)
    
    # Fill with identical data
    for i in range(100):
        h1.Fill(np.random.normal(5, 2))
        h2.Fill(np.random.normal(5, 2))
    
    # Create slightly different histograms
    h3 = ROOT.TH1F("h3", "Histogram 3", 10, 0, 10)
    h4 = ROOT.TH1F("h4", "Histogram 4", 10, 0, 10)
    
    # Fill with slightly different data
    for i in range(100):
        h3.Fill(np.random.normal(5, 2))
        h4.Fill(np.random.normal(5.5, 2))
    
    # Create very different histograms
    h5 = ROOT.TH1F("h5", "Histogram 5", 10, 0, 10)
    h6 = ROOT.TH1F("h6", "Histogram 6", 10, 0, 10)
    
    # Fill with very different data
    for i in range(100):
        h5.Fill(np.random.normal(3, 1))
        h6.Fill(np.random.normal(7, 1))
    
    # Create weighted histogram
    h7 = ROOT.TH1F("h7", "Histogram 7", 10, 0, 10)
    h7.Sumw2()  # Enable sum of weights
    
    # Fill with weighted data
    for i in range(100):
        weight = np.random.uniform(0.5, 1.5)
        h7.Fill(np.random.normal(5, 2), weight)
    
    return [(h1, h2, "identical"), (h3, h4, "slightly different"), (h5, h6, "very different"), (h1, h7, "weighted")]

ROOT.gInterpreter.Declare(
    """
auto MyChi2Test(const TH1* a, const TH1* b, Option_t* option){
    Double_t chi2 = 0;
    Int_t ndf = 0, igood = 0;
    Double_t* res = 0;

    // Double_t prob = a->Chi2TestX(b, chi2, ndf, igood, option, res);
    Double_t prob = 0;
    return std::make_tuple(prob, chi2, ndf, igood);
}
"""
)

def compare_chi2_implementations(h1, h2, option="UU"):
    """
    Compare the Python implementation of Chi2TestX with the ROOT implementation.
    
    Parameters:
    -----------
    h1, h2 : ROOT.TH1
        The histograms to compare
    option : str
        Options for the test
        
    Returns:
    --------
    dict: Comparison of results from both implementations
    """
    # Python implementation
    py_prob, py_chi2, py_ndf, py_igood = chi2_test_x(h1, h2, option)
    
    # ROOT implementation
    root_chi2 = ctypes.c_double(0)
    root_ndf = ctypes.c_int(0)
    root_igood = ctypes.c_int(0)
    res = ctypes.POINTER(ctypes.c_double)()
    root_prob = h1.Chi2TestX(h2, root_chi2, root_ndf, root_igood, option, res)
    
    return {
        "python": {
            "prob": py_prob,
            "chi2": py_chi2,
            "ndf": py_ndf,
            "igood": py_igood
        },
        "root": {
            "prob": root_prob,
            "chi2": root_chi2.value,
            "ndf": root_ndf.value,
            "igood": root_igood.value
        },
        "diff": {
            "prob": abs(py_prob - root_prob),
            "chi2": abs(py_chi2 - root_chi2.value),
            "ndf": abs(py_ndf - root_ndf.value),
            "igood": abs(py_igood - root_igood.value)
        }
    }



def test_chi2_implementations():
    """Test the Python implementation against the ROOT implementation."""
    print("Testing Chi2TestX implementations...")
    print("-" * 80)
    
    histogram_pairs = create_test_histograms()
    
    for h1, h2, desc in histogram_pairs:
        print(f"\nTesting {desc} histograms:")
        print(f"  Histogram 1: {h1.GetName()} - Entries: {h1.GetEntries()}")
        print(f"  Histogram 2: {h2.GetName()} - Entries: {h2.GetEntries()}")
        
        # Test with different options
        for option in ["UU", "UW", "WW", "UUOF", "UUUF", "UUOFUF"]:
            print(f"\n  Option: {option}")
            results = compare_chi2_implementations(h1, h2, option)
            
            # Print results
            print("    Python implementation:")
            print(f"      p-value: {results['python']['prob']:.6f}")
            print(f"      chi2: {results['python']['chi2']:.6f}")
            print(f"      ndf: {results['python']['ndf']}")
            print(f"      igood: {results['python']['igood']}")
            
            print("    ROOT implementation:")
            print(f"      p-value: {results['root']['prob']:.6f}")
            print(f"      chi2: {results['root']['chi2']:.6f}")
            print(f"      ndf: {results['root']['ndf']}")
            print(f"      igood: {results['root']['igood']}")
            
            print("    Differences:")
            print(f"      p-value diff: {results['diff']['prob']:.6f}")
            print(f"      chi2 diff: {results['diff']['chi2']:.6f}")
            print(f"      ndf diff: {results['diff']['ndf']}")
            print(f"      igood diff: {results['diff']['igood']}")
            
            # Check if the differences are acceptable
            if (results['diff']['prob'] < 1e-6 and 
                results['diff']['chi2'] < 1e-6 and 
                results['diff']['ndf'] == 0 and 
                results['diff']['igood'] == 0):
                print("    ✅ Implementations match!")
            else:
                print("    ❌ Implementations differ!")

if __name__ == "__main__":
    test_chi2_implementations() 