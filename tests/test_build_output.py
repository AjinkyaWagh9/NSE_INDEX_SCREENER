# tests/test_build_output.py
import pandas as pd
from openpyxl import load_workbook
from ranking.build_output import write_shortlist_xlsx

def _df(**cols):
    return pd.DataFrame(cols)

def test_writes_expected_sheets(tmp_path):
    by_aum = _df(fund_id=["A"], matched_index=["NIFTY 50"], aum_cr=[5000.0], rank_aum=[1])
    by_comp = _df(fund_id=["A"], matched_index=["NIFTY 50"], composite_score=[1.0], rank_composite=[1])
    unresolved = _df(fund_id=["E"], name=["E"], matched_index=["NIFTY 50"])
    below = _df(fund_id=["D"], name=["D"], aum_cr=[5.0])
    out = tmp_path/"07.xlsx"
    write_shortlist_xlsx(out, by_aum, by_comp, by_aum, by_comp, unresolved, below,
                         weights={"aum":0.5,"ter":0.3,"liq":0.2})
    wb = load_workbook(out)
    for s in ["Rank by AUM","Rank by Composite","Top 3 by AUM","Top 3 by Composite",
              "Unresolved AUM","Below 10cr","Summary"]:
        assert s in wb.sheetnames

def test_summary_reports_counts(tmp_path):
    by_aum = _df(fund_id=["A","B"], matched_index=["NIFTY 50","NIFTY 50"], aum_cr=[5000.0,1000.0], rank_aum=[1,2])
    by_comp = by_aum.assign(composite_score=[1.0,0.0], rank_composite=[1,2])
    unresolved = _df(fund_id=["E"], name=["E"], matched_index=["NIFTY 50"])
    below = _df(fund_id=[], name=[], aum_cr=[])
    out = tmp_path/"07.xlsx"
    write_shortlist_xlsx(out, by_aum, by_comp, by_aum, by_comp, unresolved, below)
    wb = load_workbook(out)
    summary = {r[0]: r[1] for r in wb["Summary"].iter_rows(values_only=True) if r[0]}
    assert summary["Qualifying funds"] == 2
    assert summary["Unresolved AUM"] == 1
