from screener.core.universe import IndexInfo


def make_info(id="NIFTY 50", tab="equity", category="Broad Market", source="kite", token=1,
              code=None, etfs=("A ETF",), funds=("A Index Fund",)):
    return IndexInfo(id=id, display_name=id.title(), tab=tab, category=category, source=source,
                     kite_symbol=id if source == "kite" else None,
                     kite_instrument_token=token if source == "kite" else None,
                     nav_scheme_code=code, nav_fund_name="Proxy Fund" if source == "amfi" else None,
                     etfs=tuple(etfs), index_funds=tuple(funds))
