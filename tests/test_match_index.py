from fetch_etf_index_data import match_index


def test_specific_index_beats_parent():
    assert match_index("UTI Nifty 200 Momentum 30 Index Fund") == "NIFTY200 MOMENTUM 30"
    assert match_index("ICICI Prudential Nifty 100 Low Vol 30 ETF") == "NIFTY100 LOW VOLATILITY 30"
    assert match_index("DSP Nifty 50 Equal Weight ETF") == "NIFTY50 EQUAL WEIGHT"
    assert match_index("DSP BSE SENSEX Next 30 ETF") == "S&P BSE SENSEX NEXT 30"


def test_plain_broad_index_still_matches():
    assert match_index("UTI Nifty 50 Index Fund") == "NIFTY 50"
    assert match_index("HDFC BSE Sensex Index Fund") == "S&P BSE SENSEX"
    assert match_index("SENSEX") == "S&P BSE SENSEX"


def test_target_maturity_split_by_date():
    a = match_index("Kotak Nifty SDL Apr 2027 Top 12 Equal Weight Index Fund")
    b = match_index("Kotak Nifty SDL Apr 2032 Top 12 Equal Weight Index Fund")
    assert a != b and "2027" in a and "2032" in b


def test_hybrid_kept_separate():
    assert "HYBRID" in match_index("Motilal Oswal Nifty Midcap150 Plus 8-13 yr G-Sec 70:30 Index Fund")


def test_pse_and_bse_housing():
    assert match_index("Motilal Oswal Nifty PSE ETF") == "NIFTY PSE"
    assert match_index("CPSE ETF") == "NIFTY CPSE"
    assert match_index("UTI BSE Housing Index Fund") == "BSE HOUSING"
