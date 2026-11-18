"""Write the final multi-sheet shortlist workbook."""
from datetime import datetime
import pandas as pd


def write_shortlist_xlsx(out_path, by_aum, by_composite, top_aum, top_composite,
                         unresolved, below, df_indices=None, df_benchmarks=None, weights=None):
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        by_aum.to_excel(writer, sheet_name="Rank by AUM", index=False)
        by_composite.to_excel(writer, sheet_name="Rank by Composite", index=False)
        top_aum.to_excel(writer, sheet_name="Top 3 by AUM", index=False)
        top_composite.to_excel(writer, sheet_name="Top 3 by Composite", index=False)
        unresolved.to_excel(writer, sheet_name="Unresolved AUM", index=False)
        below.to_excel(writer, sheet_name="Below 10cr", index=False)
        if df_indices is not None and not df_indices.empty:
            df_indices.to_excel(writer, sheet_name="All NSE Indices", index=False)
        if df_benchmarks is not None and not df_benchmarks.empty:
            df_benchmarks.to_excel(writer, sheet_name="Benchmark Codes", index=False)

        w = weights or {"aum": 0.5, "ter": 0.3, "liq": 0.2}
        stats = {
            "Metric": [
                "Qualifying funds", "Indices with >=1 qualifying fund",
                "Unresolved AUM", "Below 10cr",
                "Composite weights (AUM/TER/liq)", "Generated",
            ],
            "Value": [
                len(by_aum),
                by_aum["matched_index"].nunique() if len(by_aum) else 0,
                len(unresolved), len(below),
                f'{w["aum"]}/{w["ter"]}/{w["liq"]}',
                datetime.now().strftime("%Y-%m-%d %H:%M"),
            ],
        }
        pd.DataFrame(stats).to_excel(writer, sheet_name="Summary", index=False)
