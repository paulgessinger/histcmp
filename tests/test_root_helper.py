from histcmp.root_helpers import _process_axis_title
def test_delta_r():
    res = _process_axis_title("Closest track #DeltaR")
    assert res == "Closest track $\DeltaR$"
