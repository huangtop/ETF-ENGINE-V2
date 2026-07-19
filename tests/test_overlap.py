from etf_engine.services.holding_service import overlap

def test_overlap():
    r=overlap([{"holding_symbol":"A","weight":.3}],[{"holding_symbol":"A","weight":.2}])
    assert r["overlap_ratio"] == .2
