#!/usr/bin/env python3
"""
ETF & Index Fund Data Automation
=================================
Downloads and maps:
  1. All NSE/Nifty indices (equity, sectoral, thematic, strategy, fixed income)
  2. All ETFs listed on NSE with trading data
  3. All mutual fund schemes (ETFs + Index Funds) from AMFI
  4. Benchmark codes from NiftyIndices.com
  5. Maps ETFs/Index Funds → underlying Nifty indices
  6. Outputs a final ranked spreadsheet

Sources:
  - NSE India API (allIndices, etf)
  - AMFI NAVAll.txt (all scheme data)
  - mfapi.in (scheme metadata)
  - NiftyIndices.com (benchmark codes PDF)

Usage:
  python3 fetch_etf_index_data.py

Output:
  - data/01_nse_indices.csv          → All NSE indices
  - data/02_nse_etfs.csv             → All NSE-listed ETFs
  - data/03_amfi_etf_index_schemes.csv → AMFI ETF & Index Fund schemes
  - data/04_benchmark_codes.csv      → Nifty benchmark codes
  - data/05_mfapi_schemes.csv        → mfapi scheme catalog (ETF/Index only)
  - data/06_mapped_funds.csv         → Funds mapped to indices
  - data/07_final_shortlist.xlsx     → Final ranked spreadsheet
"""

import os
import re
import sys
import json
import time
import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import requests
import pandas as pd

warnings.filterwarnings("ignore")

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# AUM threshold in ₹ crore
AUM_THRESHOLD_CR = 10


# ─── HTTP Session ────────────────────────────────────────────────────────────

def get_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


# ─── Step 1: Fetch All NSE Indices ──────────────────────────────────────────

def fetch_nse_indices(session):
    """Fetch all indices from NSE allIndices API."""
    log.info("Step 1: Fetching all NSE indices...")
    url = "https://www.nseindia.com/api/allIndices"
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        indices = data.get("data", [])
        log.info(f"  → Fetched {len(indices)} indices")

        df = pd.DataFrame(indices)
        # Keep useful columns
        cols_keep = [
            "index", "indexSymbol", "key", "last", "open", "high", "low",
            "previousClose", "variation", "percentChange",
            "yearHigh", "yearLow",
            "perChange365d", "perChange30d",
        ]
        cols_available = [c for c in cols_keep if c in df.columns]
        df = df[cols_available]
        df.rename(columns={
            "index": "Index_Name",
            "indexSymbol": "Index_Symbol",
            "key": "Category",
            "last": "Last_Value",
        }, inplace=True)

        outpath = DATA_DIR / "01_nse_indices.csv"
        df.to_csv(outpath, index=False)
        log.info(f"  → Saved to {outpath}")
        return df
    except Exception as e:
        log.error(f"  ✗ Failed to fetch NSE indices: {e}")
        return pd.DataFrame()


# ─── Step 2: Fetch All NSE ETFs ─────────────────────────────────────────────

def fetch_nse_etfs(session):
    """Fetch all ETFs listed on NSE with market data."""
    log.info("Step 2: Fetching all NSE-listed ETFs...")
    url = "https://www.nseindia.com/api/etf"
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        etfs = data.get("data", [])
        log.info(f"  → Fetched {len(etfs)} ETFs")

        df = pd.DataFrame(etfs)
        df.rename(columns={
            "symbol": "Symbol",
            "assets": "Underlying_Asset",
            "ltP": "LTP",
            "qty": "Volume",
            "trdVal": "Traded_Value",
            "nav": "NAV",
            "wkhi": "52W_High",
            "wklo": "52W_Low",
            "prevClose": "Prev_Close",
            "perChange365d": "Change_1Y_pct",
            "perChange30d": "Change_1M_pct",
        }, inplace=True)

        outpath = DATA_DIR / "02_nse_etfs.csv"
        df.to_csv(outpath, index=False)
        log.info(f"  → Saved to {outpath}")
        return df
    except Exception as e:
        log.error(f"  ✗ Failed to fetch NSE ETFs: {e}")
        return pd.DataFrame()


# ─── Step 3: Fetch AMFI Scheme Data ─────────────────────────────────────────

def fetch_amfi_schemes(session):
    """Parse AMFI NAVAll.txt for ETF and Index Fund schemes."""
    log.info("Step 3: Fetching AMFI NAVAll.txt for ETF & Index Fund schemes...")
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        lines = r.text.strip().split("\n")
        log.info(f"  → Downloaded {len(lines)} lines from NAVAll.txt")

        # Parse structured data
        schemes = []
        current_category = ""
        current_amc = ""

        for line in lines:
            line = line.strip().rstrip("\r")
            if not line:
                continue

            # Category header lines
            if line.startswith("Open Ended Schemes") or line.startswith("Close Ended Schemes"):
                current_category = line
                continue

            # Lines with semicolons are scheme data
            if ";" in line:
                parts = line.split(";")
                if len(parts) >= 8:
                    scheme = {
                        "Scheme_Code": parts[0].strip(),
                        "ISIN_Growth": parts[1].strip() if parts[1].strip() != "-" else "",
                        "ISIN_Div_Reinvest": parts[2].strip() if parts[2].strip() != "-" else "",
                        "Scheme_Name": parts[3].strip(),
                        "Plan": parts[4].strip(),
                        "Option": parts[5].strip(),
                        "NAV": parts[6].strip(),
                        "Date": parts[7].strip(),
                        "AMFI_Category": current_category,
                        "AMC": current_amc,
                    }
                    schemes.append(scheme)
            else:
                # Likely an AMC name
                if not line.startswith("Scheme Code"):
                    current_amc = line

        df_all = pd.DataFrame(schemes)
        log.info(f"  → Parsed {len(df_all)} total schemes")

        # Filter for ETF and Index Fund schemes
        etf_index_mask = (
            df_all["AMFI_Category"].str.contains("ETF", case=False, na=False) |
            df_all["AMFI_Category"].str.contains("Index Fund", case=False, na=False) |
            df_all["Scheme_Name"].str.contains("ETF", case=False, na=False) |
            df_all["Scheme_Name"].str.contains("Index Fund", case=False, na=False)
        )
        df_etf_idx = df_all[etf_index_mask].copy()
        log.info(f"  → Filtered to {len(df_etf_idx)} ETF/Index Fund scheme entries")

        # Classify scheme type
        def classify(row):
            cat = str(row["AMFI_Category"]).upper()
            name = str(row["Scheme_Name"]).upper()
            if "ETF" in cat or "ETF" in name:
                if "GOLD" in name or "SILVER" in name:
                    return "Commodity ETF"
                elif "G-SEC" in name or "BOND" in name or "DEBT" in name or "LIQUID" in name:
                    return "Debt ETF"
                else:
                    return "Equity ETF"
            elif "INDEX" in cat or "INDEX" in name:
                return "Index Fund"
            return "Other"

        df_etf_idx["Scheme_Type"] = df_etf_idx.apply(classify, axis=1)

        outpath = DATA_DIR / "03_amfi_etf_index_schemes.csv"
        df_etf_idx.to_csv(outpath, index=False)
        log.info(f"  → Saved to {outpath}")
        return df_etf_idx
    except Exception as e:
        log.error(f"  ✗ Failed to fetch AMFI data: {e}")
        return pd.DataFrame()


# ─── Step 4: Parse Benchmark Codes ──────────────────────────────────────────

def fetch_benchmark_codes(session):
    """Download and parse Nifty benchmark codes PDF."""
    log.info("Step 4: Fetching Nifty benchmark codes...")
    url = "https://www.niftyindices.com/BenchmarkCodes/nifty_indices_benchmark_codes.pdf"
    pdf_path = DATA_DIR / "nifty_benchmark_codes.pdf"
    try:
        r = session.get(url, timeout=15)
        r.raise_for_status()
        with open(pdf_path, "wb") as f:
            f.write(r.content)
        log.info(f"  → Downloaded benchmark codes PDF ({len(r.content)} bytes)")

        # Parse the PDF
        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            all_text = ""
            for page in reader.pages:
                all_text += page.extract_text() + "\n"
        except ImportError:
            log.warning("  pypdf not available, trying PyPDF2...")
            import PyPDF2
            reader = PyPDF2.PdfReader(str(pdf_path))
            all_text = ""
            for page in reader.pages:
                all_text += page.extract_text() + "\n"

        # Extract benchmark entries: Sr. No, Code, Name
        entries = []
        # Pattern: number NSE_X_NNN Name
        pattern = re.compile(r"(\d+)\s+(NSE_[A-Z]_\d+)\s+(.+?)(?=\d+\s+NSE_|\Z)", re.DOTALL)
        matches = pattern.findall(all_text)
        for sr, code, name in matches:
            name = " ".join(name.split())  # Clean whitespace
            entries.append({
                "Sr_No": int(sr),
                "Benchmark_Code": code,
                "Benchmark_Name": name.strip(),
            })

        if not entries:
            # Fallback: line-by-line
            for line in all_text.split("\n"):
                line = line.strip()
                m = re.match(r"(\d+)\s+(NSE_[A-Z]_\d+)\s+(.+)", line)
                if m:
                    entries.append({
                        "Sr_No": int(m.group(1)),
                        "Benchmark_Code": m.group(2),
                        "Benchmark_Name": m.group(3).strip(),
                    })

        df = pd.DataFrame(entries)

        # Classify: E=Equity, D=Debt, H=Hybrid
        def classify_bench(code):
            if "_E_" in code:
                return "Equity"
            elif "_D_" in code:
                return "Debt"
            elif "_H_" in code:
                return "Hybrid"
            return "Other"

        df["Asset_Class"] = df["Benchmark_Code"].apply(classify_bench)
        log.info(f"  → Parsed {len(df)} benchmark codes "
                 f"(Equity: {(df['Asset_Class']=='Equity').sum()}, "
                 f"Debt: {(df['Asset_Class']=='Debt').sum()}, "
                 f"Hybrid: {(df['Asset_Class']=='Hybrid').sum()})")

        outpath = DATA_DIR / "04_benchmark_codes.csv"
        df.to_csv(outpath, index=False)
        log.info(f"  → Saved to {outpath}")
        return df
    except Exception as e:
        log.error(f"  ✗ Failed to fetch benchmark codes: {e}")
        return pd.DataFrame()


# ─── Step 5: Fetch mfapi.in Scheme Catalog ──────────────────────────────────

def fetch_mfapi_catalog(session):
    """Fetch scheme list from mfapi.in (community API wrapping AMFI data)."""
    log.info("Step 5: Fetching mfapi.in scheme catalog...")
    url = "https://api.mfapi.in/mf"
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        all_schemes = r.json()
        log.info(f"  → Fetched {len(all_schemes)} total schemes from mfapi.in")

        # Filter for ETF/Index Fund schemes
        keywords = ["ETF", "INDEX FUND", "INDEX-", "NIFTY", "SENSEX", "BSE"]
        filtered = []
        for s in all_schemes:
            name_upper = s.get("schemeName", "").upper()
            if any(k in name_upper for k in keywords):
                filtered.append(s)

        df = pd.DataFrame(filtered)
        df.rename(columns={
            "schemeCode": "Scheme_Code",
            "schemeName": "Scheme_Name",
            "isinGrowth": "ISIN_Growth",
            "isinDivReinvestment": "ISIN_Div_Reinvest",
        }, inplace=True)
        log.info(f"  → Filtered to {len(df)} ETF/Index/Nifty/Sensex schemes")

        outpath = DATA_DIR / "05_mfapi_schemes.csv"
        df.to_csv(outpath, index=False)
        log.info(f"  → Saved to {outpath}")
        return df
    except Exception as e:
        log.error(f"  ✗ Failed to fetch mfapi catalog: {e}")
        return pd.DataFrame()


# ─── Step 6: Map Funds to Indices ────────────────────────────────────────────

# Mapping of common index name variants to canonical names
INDEX_NAME_PATTERNS = {
    # Broad Market
    r"NIFTY\s*50(?!\d)": "NIFTY 50",
    r"NIFTY\s*NEXT\s*50": "NIFTY NEXT 50",
    r"NIFTY\s*100(?!\d)": "NIFTY 100",
    r"NIFTY\s*200(?!\d)": "NIFTY 200",
    r"NIFTY\s*500(?!\d)": "NIFTY 500",
    r"NIFTY\s*MIDCAP\s*50(?!\d)": "NIFTY MIDCAP 50",
    r"NIFTY\s*MIDCAP\s*100": "NIFTY MIDCAP 100",
    r"NIFTY\s*MIDCAP\s*150": "NIFTY MIDCAP 150",
    r"NIFTY\s*SMALLCAP\s*50(?!\d)": "NIFTY SMALLCAP 50",
    r"NIFTY\s*SMALLCAP\s*100": "NIFTY SMALLCAP 100",
    r"NIFTY\s*SMALLCAP\s*250": "NIFTY SMALLCAP 250",
    r"NIFTY\s*SMALLCAP\s*500": "NIFTY SMALLCAP 500",
    r"NIFTY\s*MIDSMALLCAP\s*400": "NIFTY MIDSMALLCAP 400",
    r"NIFTY\s*LARGEMIDCAP\s*250": "NIFTY LARGEMIDCAP 250",
    r"NIFTY\s*TOTAL\s*MARKET(?!\s*MOM)": "NIFTY TOTAL MARKET",
    r"NIFTY\s*MICROCAP\s*250": "NIFTY MICROCAP 250",
    r"NIFTY\s*MIDCAP\s*SELECT": "NIFTY MIDCAP SELECT",
    r"NIFTY500\s*MULTICAP\s*50.?25.?25": "NIFTY500 MULTICAP 50:25:25",
    r"NIFTY\s*INDIA\s*FPI\s*150": "NIFTY INDIA FPI 150",

    # Sectoral
    r"NIFTY\s*BANK": "NIFTY BANK",
    r"NIFTY\s*IT\b": "NIFTY IT",
    r"NIFTY\s*PHARMA": "NIFTY PHARMA",
    r"NIFTY\s*AUTO(?!\s*M)": "NIFTY AUTO",
    r"NIFTY\s*FMCG": "NIFTY FMCG",
    r"NIFTY\s*METAL": "NIFTY METAL",
    r"NIFTY\s*REALTY": "NIFTY REALTY",
    r"NIFTY\s*PSU\s*BANK": "NIFTY PSU BANK",
    r"NIFTY\s*PRIVATE\s*BANK": "NIFTY PRIVATE BANK",
    r"NIFTY\s*MEDIA": "NIFTY MEDIA",
    r"NIFTY\s*FINANCIAL\s*SERVICES?\s*25.?50": "NIFTY FINANCIAL SERVICES 25/50",
    r"NIFTY\s*FINANCIAL\s*SERVICES?\s*EX.?BANK": "NIFTY FINANCIAL SERVICES EX-BANK",
    r"NIFTY\s*FINANCIAL\s*SERVICES?(?!\s*(25|EX|$))": "NIFTY FINANCIAL SERVICES",
    r"NIFTY\s*HEALTHCARE": "NIFTY HEALTHCARE INDEX",
    r"NIFTY\s*CONSUMER\s*DURABLES": "NIFTY CONSUMER DURABLES",
    r"NIFTY\s*OIL\s*(&|AND)\s*GAS": "NIFTY OIL & GAS",
    r"NIFTY\s*CEMENT": "NIFTY CEMENT",

    # Thematic
    r"NIFTY\s*CPSE": "NIFTY CPSE",
    r"NIFTY\s*INDIA\s*CONSUMPTION": "NIFTY INDIA CONSUMPTION",
    r"NIFTY\s*COMMODIT(Y|IES)": "NIFTY COMMODITIES",
    r"NIFTY\s*ENERGY": "NIFTY ENERGY",
    r"NIFTY\s*INFRASTRUCTURE(?!\s*&)": "NIFTY INFRASTRUCTURE",
    r"NIFTY\s*MNC": "NIFTY MNC",
    r"NIFTY\s*PSE(?!\s)": "NIFTY PSE",
    r"NIFTY\s*INDIA\s*DEFENCE": "NIFTY INDIA DEFENCE",
    r"NIFTY\s*INDIA\s*MANUFACTUR": "NIFTY INDIA MANUFACTURING",
    r"NIFTY\s*INDIA\s*DIGITAL": "NIFTY INDIA DIGITAL",
    r"NIFTY\s*CAPITAL\s*MARKETS": "NIFTY CAPITAL MARKETS",
    r"NIFTY\s*EV\s*(&|AND)\s*NEW\s*AGE": "NIFTY EV & NEW AGE AUTOMOTIVE",
    r"NIFTY\s*INDIA\s*TOURISM": "NIFTY INDIA TOURISM",
    r"NIFTY\s*MOBILITY": "NIFTY MOBILITY",
    r"NIFTY\s*HOUSING(?!\s*FIN)": "NIFTY HOUSING",
    r"NIFTY\s*CORE\s*HOUSING": "NIFTY CORE HOUSING",
    r"NIFTY\s*NON.?CYCLICAL": "NIFTY NON-CYCLICAL CONSUMER",
    r"NIFTY\s*RURAL": "NIFTY RURAL",
    r"NIFTY\s*INDIA\s*INTERNET": "NIFTY INDIA INTERNET",
    r"NIFTY\s*CONGLOMERATE": "NIFTY CONGLOMERATE 50",
    r"NIFTY500\s*MULTICAP\s*INDIA\s*MANUFACTUR": "NIFTY500 MULTICAP INDIA MANUFACTURING 50:30:20",
    r"NIFTY500\s*MULTICAP\s*INFRASTR": "NIFTY500 MULTICAP INFRASTRUCTURE 50:30:20",

    # Strategy / Factor
    r"NIFTY\s*50\s*EQUAL\s*WEIGHT": "NIFTY50 EQUAL WEIGHT",
    r"NIFTY\s*100\s*EQUAL\s*WEIGHT": "NIFTY100 EQUAL WEIGHT",
    r"NIFTY\s*500\s*EQUAL\s*WEIGHT": "NIFTY500 EQUAL WEIGHT",
    r"NIFTY\s*50\s*VALUE\s*20": "NIFTY50 VALUE 20",
    r"NIFTY\s*100\s*QUALITY\s*30": "NIFTY100 QUALITY 30",
    r"NIFTY\s*100\s*LOW\s*VOLAT": "NIFTY100 LOW VOLATILITY 30",
    r"NIFTY\s*200\s*QUALITY\s*30": "NIFTY200 QUALITY 30",
    r"NIFTY\s*200\s*MOMENTUM\s*30": "NIFTY200 MOMENTUM 30",
    r"NIFTY\s*200\s*ALPHA\s*30": "NIFTY200 ALPHA 30",
    r"NIFTY\s*200\s*VALUE\s*30": "NIFTY200 VALUE 30",
    r"NIFTY\s*500\s*MOMENTUM\s*50": "NIFTY500 MOMENTUM 50",
    r"NIFTY\s*500\s*VALUE\s*50": "NIFTY500 VALUE 50",
    r"NIFTY\s*500\s*QUALITY\s*50": "NIFTY500 QUALITY 50",
    r"NIFTY\s*500\s*LOW\s*VOLAT": "NIFTY500 LOW VOLATILITY 50",
    r"NIFTY\s*ALPHA\s*50": "NIFTY ALPHA 50",
    r"NIFTY\s*ALPHA\s*LOW.?VOLAT": "NIFTY ALPHA LOW-VOLATILITY 30",
    r"NIFTY\s*LOW\s*VOLATILITY\s*50": "NIFTY LOW VOLATILITY 50",
    r"NIFTY\s*DIVIDEND\s*OPPORTUNIT": "NIFTY DIVIDEND OPPORTUNITIES 50",
    r"NIFTY\s*GROWTH\s*SECTORS?\s*15": "NIFTY GROWTH SECTORS 15",
    r"NIFTY\s*MIDCAP\s*150\s*QUALITY\s*50": "NIFTY MIDCAP150 QUALITY 50",
    r"NIFTY\s*MIDCAP\s*150\s*MOMENTUM\s*50": "NIFTY MIDCAP150 MOMENTUM 50",
    r"NIFTY\s*SMALLCAP\s*250\s*QUALITY\s*50": "NIFTY SMALLCAP250 QUALITY 50",
    r"NIFTY\s*TOP\s*10\s*EQUAL": "NIFTY TOP 10 EQUAL WEIGHT",
    r"NIFTY\s*TOTAL\s*MARKET\s*MOMENTUM\s*QUALITY": "NIFTY TOTAL MARKET MOMENTUM QUALITY 50",
    r"NIFTY\s*500\s*MULTICAP\s*MOMENTUM\s*QUALITY": "NIFTY500 MULTICAP MOMENTUM QUALITY 50",

    # Fixed Income
    r"NIFTY\s*8.?13\s*(YR|YEAR)\s*G.?SEC": "NIFTY 8-13 YR G-SEC",
    r"NIFTY\s*10\s*(YR|YEAR)\s*BENCHMARK\s*G.?SEC": "NIFTY 10 YR BENCHMARK G-SEC",
    r"NIFTY\s*5\s*(YR|YEAR)\s*BENCHMARK\s*G.?SEC": "NIFTY 5 YR BENCHMARK G-SEC",
    r"NIFTY\s*4.?8\s*(YR|YEAR)\s*G.?SEC": "NIFTY 4-8 YR G-SEC INDEX",
    r"NIFTY\s*BHARAT\s*BOND.*2030": "NIFTY BHARAT BOND INDEX - APRIL 2030",
    r"NIFTY\s*BHARAT\s*BOND.*2031": "NIFTY BHARAT BOND INDEX - APRIL 2031",
    r"NIFTY\s*BHARAT\s*BOND.*2032": "NIFTY BHARAT BOND INDEX - APRIL 2032",
    r"NIFTY\s*BHARAT\s*BOND.*2033": "NIFTY BHARAT BOND INDEX - APRIL 2033",
    r"NIFTY\s*1D\s*RATE": "NIFTY 1D RATE",

    # More Thematic / Sectoral
    r"NIFTY\s*INDIA\s*RAILWAYS?\s*PSU": "NIFTY INDIA RAILWAYS PSU",
    r"NIFTY\s*SERVICES?\s*SECTOR": "NIFTY SERVICES SECTOR",
    r"NIFTY\s*IPO": "NIFTY IPO",
    r"NIFTY\s*WAVES": "NIFTY WAVES",
    r"NIFTY\s*INDIA\s*INFRASTR.*LOGIST": "NIFTY INDIA INFRASTRUCTURE & LOGISTICS",
    r"NIFTY\s*MIDSMALL\s*INDIA\s*CONSUM": "NIFTY MIDSMALL INDIA CONSUMPTION",
    r"NIFTY\s*MIDSMALL\s*FINANCIAL": "NIFTY MIDSMALL FINANCIAL SERVICES",
    r"NIFTY\s*MIDSMALL\s*HEALTHCARE": "NIFTY MIDSMALL HEALTHCARE",
    r"NIFTY\s*MIDSMALL\s*IT": "NIFTY MIDSMALL IT & TELECOM",
    r"NIFTY\s*500\s*HEALTHCARE": "NIFTY500 HEALTHCARE",
    r"NIFTY\s*REITS?\s*(&|AND)\s*REALTY": "NIFTY REITS & REALTY",
    r"NIFTY\s*100\s*ESG\b": "NIFTY100 ESG",
    r"NIFTY\s*100\s*LIQUID\s*15": "NIFTY100 LIQUID 15",
    r"NIFTY\s*100\s*ALPHA\s*30": "NIFTY100 ALPHA 30",
    r"NIFTY\s*MIDCAP\s*LIQUID\s*15": "NIFTY MIDCAP LIQUID 15",
    r"NIFTY\s*SHARIAH\s*25": "NIFTY SHARIAH 25",
    r"NIFTY\s*50\s*SHARIAH": "NIFTY50 SHARIAH",
    r"NIFTY\s*500\s*SHARIAH": "NIFTY500 SHARIAH",
    r"NIFTY\s*SME\s*EMERGE": "NIFTY SME EMERGE",
    r"NIFTY\s*TRANSPORTATION": "NIFTY TRANSPORTATION & LOGISTICS",
    r"NIFTY\s*CHEMICALS": "NIFTY CHEMICALS",
    r"NIFTY\s*500\s*FLEXICAP\s*QUALITY": "NIFTY500 FLEXICAP QUALITY 30",
    r"NIFTY\s*500\s*MULTIFACTOR": "NIFTY500 MULTIFACTOR MQVLV 50",
    r"NIFTY\s*ALPHA\s*QUALITY\s*VALUE": "NIFTY ALPHA QUALITY VALUE LOW-VOLATILITY 30",
    r"NIFTY\s*ALPHA\s*QUALITY\s*LOW": "NIFTY ALPHA QUALITY LOW-VOLATILITY 30",
    r"NIFTY\s*QUALITY\s*LOW": "NIFTY QUALITY LOW-VOLATILITY 30",
    r"NIFTY\s*HIGH\s*BETA": "NIFTY HIGH BETA 50",
    r"NIFTY\s*TOP\s*15\s*EQUAL": "NIFTY TOP 15 EQUAL WEIGHT",
    r"NIFTY\s*TOP\s*20\s*EQUAL": "NIFTY TOP 20 EQUAL WEIGHT",
    r"NIFTY\s*MIDSMALLCAP\s*400\s*MOMENTUM": "NIFTY MIDSMALLCAP400 MOMENTUM QUALITY 100",
    r"NIFTY\s*SMALLCAP\s*250\s*MOMENTUM": "NIFTY SMALLCAP250 MOMENTUM QUALITY 100",
    r"NIFTY\s*500\s*GROWTH\s*50": "NIFTY500 GROWTH 50",

    # Fixed income / Debt additional
    r"NIFTY\s*SDL\b": "NIFTY SDL (Target Maturity)",
    r"NIFTY\s*G.?SEC(?!\s*\d)": "NIFTY G-SEC (Target Maturity)",
    r"NIFTY\s*PSU\s*BOND": "NIFTY PSU BOND (Target Maturity)",
    r"NIFTY\s*AAA\b": "NIFTY AAA BOND (Target Maturity)",
    r"NIFTY\s*COMPOSITE\s*G.?SEC": "NIFTY COMPOSITE G-SEC INDEX",

    # BSE / Sensex indices
    r"S&?P\s*BSE\s*SENSEX|BSE\s*SENSEX": "S&P BSE SENSEX",
    r"BSE\s*SENSEX\s*NEXT\s*50": "S&P BSE SENSEX NEXT 50",
    r"BSE\s*SENSEX\s*NEXT\s*30": "S&P BSE SENSEX NEXT 30",
    r"BSE\s*500(?!\d)": "S&P BSE 500",
    r"BSE\s*200(?!\d)": "S&P BSE 200",
    r"BSE\s*TOTAL\s*MARKET": "BSE TOTAL MARKET",
    r"BSE\s*TOP\s*10\s*BANK": "BSE TOP 10 BANKS",
    r"BSE\s*PSU\s*BANK": "BSE PSU BANK INDEX",
    r"BSE\s*POWER": "BSE POWER INDEX",
    r"BSE\s*INDIA\s*DEFENCE": "BSE INDIA DEFENCE",
    r"BSE\s*INSURANCE": "BSE INSURANCE INDEX",
    r"BSE\s*HOSPITAL": "BSE HOSPITALS INDEX",
    r"BSE\s*CAPITAL\s*MARKET": "BSE CAPITAL MARKETS & INSURANCE",
    r"BSE\s*INDIA\s*INFRASTR": "BSE INDIA INFRASTRUCTURE",
    r"BSE\s*INDIA\s*SECTOR\s*LEADER": "BSE INDIA SECTOR LEADERS",
    r"BSE\s*LIQUID\s*RATE": "BSE LIQUID RATE INDEX",
    r"BSE\s*MIDCAP\s*150": "BSE MIDCAP 150",
    r"BSE\s*SELECT\s*IPO": "BSE SELECT IPO INDEX",
    r"BSE\s*MIDSMALL\s*PRIVATE\s*BANK": "BSE MIDSMALL PRIVATE BANKS",
    r"BSE\s*LARGEMID": "BSE LARGEMID STABLE DIVIDEND 50",
    r"BSE\s*500\s*DIVIDEND": "BSE 500 DIVIDEND LEADERS",

    # CRISIL indices (debt/gilt)
    r"CRISIL\s*10\s*YEAR\s*GILT": "CRISIL 10 YEAR GILT",
    r"CRISIL\s*IBX": "CRISIL IBX INDEX",
    r"CRISIL\s*LIQUID": "CRISIL LIQUID/OVERNIGHT",
    r"CRISIL\s*BROAD\s*BASED\s*GILT": "CRISIL BROAD BASED GILT",
    r"CRISIL\s*OVERNIGHT": "CRISIL LIQUID/OVERNIGHT",

    # International
    r"HANG\s*SENG\s*TECH": "HANG SENG TECH",
    r"HANG\s*SENG": "HANG SENG",
    r"NASDAQ\s*100": "NASDAQ 100",
    r"S&?P\s*500": "S&P 500",
    r"MSCI": "MSCI INDEX",
    r"FTSE\s*INDIA": "FTSE INDIA",
}


def match_index(scheme_name):
    """Try to match a scheme name to a canonical Nifty/BSE index name."""
    name_upper = scheme_name.upper()

    # Skip pure commodity ETFs (physical gold/silver)
    if any(k in name_upper for k in ["GOLD ETF", "SILVER ETF", "GOLD FUND", "SILVER FUND"]):
        if not any(k in name_upper for k in ["NIFTY", "BSE", "SENSEX", "CRISIL"]):
            return "COMMODITY (Gold/Silver)"

    for pattern, index_name in INDEX_NAME_PATTERNS.items():
        if re.search(pattern, name_upper):
            return index_name

    return ""


def map_funds_to_indices(df_amfi, df_nse_etfs, df_nse_indices):
    """Map ETF/Index Fund schemes to their underlying indices."""
    log.info("Step 6: Mapping funds to indices...")

    records = []

    # --- Process AMFI schemes (Index Funds + some ETFs) ---
    if not df_amfi.empty:
        # Deduplicate: keep Direct Plan Growth where possible
        for _, row in df_amfi.iterrows():
            scheme_name = str(row.get("Scheme_Name", ""))
            matched_index = match_index(scheme_name)
            records.append({
                "Scheme_Code": row.get("Scheme_Code", ""),
                "Scheme_Name": scheme_name,
                "ISIN": row.get("ISIN_Growth", ""),
                "Plan": row.get("Plan", ""),
                "Option": row.get("Option", ""),
                "NAV": row.get("NAV", ""),
                "NAV_Date": row.get("Date", ""),
                "AMC": row.get("AMC", ""),
                "Scheme_Type": row.get("Scheme_Type", ""),
                "AMFI_Category": row.get("AMFI_Category", ""),
                "Matched_Index": matched_index,
                "Source": "AMFI",
            })

    # --- Process NSE ETFs (trading data) ---
    if not df_nse_etfs.empty:
        for _, row in df_nse_etfs.iterrows():
            symbol = str(row.get("Symbol", ""))
            underlying = str(row.get("Underlying_Asset", ""))
            scheme_name_for_match = underlying if underlying else symbol
            matched_index = match_index(scheme_name_for_match)

            records.append({
                "Scheme_Code": "",
                "Scheme_Name": underlying,
                "ISIN": "",
                "Plan": "",
                "Option": "",
                "NAV": row.get("NAV", ""),
                "NAV_Date": "",
                "AMC": "",
                "Scheme_Type": "ETF (NSE Listed)",
                "AMFI_Category": "",
                "Matched_Index": matched_index,
                "Source": "NSE_ETF",
                "Symbol": symbol,
                "LTP": row.get("LTP", ""),
                "Volume": row.get("Volume", ""),
                "Traded_Value": row.get("Traded_Value", ""),
                "52W_High": row.get("52W_High", ""),
                "52W_Low": row.get("52W_Low", ""),
                "Change_1Y_pct": row.get("Change_1Y_pct", ""),
                "Change_1M_pct": row.get("Change_1M_pct", ""),
            })

    df_mapped = pd.DataFrame(records)

    # Count stats
    mapped_count = (df_mapped["Matched_Index"] != "").sum()
    unmapped_count = (df_mapped["Matched_Index"] == "").sum()
    unique_indices = df_mapped.loc[
        df_mapped["Matched_Index"] != "", "Matched_Index"
    ].nunique()
    log.info(f"  → Mapped {mapped_count} schemes to {unique_indices} unique indices")
    log.info(f"  → {unmapped_count} schemes could not be matched")

    outpath = DATA_DIR / "06_mapped_funds.csv"
    df_mapped.to_csv(outpath, index=False)
    log.info(f"  → Saved to {outpath}")
    return df_mapped


# ─── Step 7: Build Final Shortlist Spreadsheet ──────────────────────────────

def build_final_shortlist(df_mapped, df_nse_indices, df_benchmarks):
    """Build the final multi-sheet Excel with index → fund mappings and rankings."""
    log.info("Step 7: Building final shortlist spreadsheet...")

    # ── Sheet 1: All NSE Indices ──
    # Already have df_nse_indices

    # ── Sheet 2: Index → Fund Mapping ──
    # Focus on matched funds, excluding commodity/international
    df_valid = df_mapped[
        (df_mapped["Matched_Index"] != "") &
        (~df_mapped["Matched_Index"].isin(["COMMODITY (Gold/Silver)", "INTERNATIONAL INDEX"]))
    ].copy()

    # ── Sheet 3: Per-Index Fund Count ──
    if not df_valid.empty:
        # For AMFI source, count unique scheme codes per index
        amfi_funds = df_valid[df_valid["Source"] == "AMFI"]
        nse_funds = df_valid[df_valid["Source"] == "NSE_ETF"]

        index_summary = []
        all_indices = sorted(df_valid["Matched_Index"].unique())
        for idx_name in all_indices:
            idx_amfi = amfi_funds[amfi_funds["Matched_Index"] == idx_name]
            idx_nse = nse_funds[nse_funds["Matched_Index"] == idx_name]

            # Count unique schemes (direct plan growth only for index funds)
            n_amfi_schemes = idx_amfi["Scheme_Code"].nunique()
            n_nse_etfs = len(idx_nse)

            # Get category from NSE indices
            cat = ""
            if not df_nse_indices.empty:
                match_rows = df_nse_indices[
                    df_nse_indices["Index_Name"].str.upper() == idx_name.upper()
                ]
                if not match_rows.empty:
                    cat = match_rows.iloc[0].get("Category", "")

            index_summary.append({
                "Index_Name": idx_name,
                "Category": cat,
                "AMFI_Schemes_Count": n_amfi_schemes,
                "NSE_ETFs_Count": n_nse_etfs,
                "Total_Products": n_amfi_schemes + n_nse_etfs,
            })

        df_summary = pd.DataFrame(index_summary)
        df_summary.sort_values("Total_Products", ascending=False, inplace=True)
    else:
        df_summary = pd.DataFrame()

    # ── Sheet 4: NSE ETFs ranked by traded value (proxy for liquidity/AUM) ──
    if not nse_funds.empty:
        df_nse_ranked = nse_funds.copy()
        df_nse_ranked["Traded_Value"] = pd.to_numeric(
            df_nse_ranked["Traded_Value"], errors="coerce"
        )
        df_nse_ranked.sort_values("Traded_Value", ascending=False, inplace=True)
    else:
        df_nse_ranked = pd.DataFrame()

    # ── Sheet 5: Benchmark Codes ──
    # Already have df_benchmarks

    # ── Write to Excel ──
    outpath = DATA_DIR / "07_final_shortlist.xlsx"
    try:
        with pd.ExcelWriter(outpath, engine="openpyxl") as writer:
            if not df_nse_indices.empty:
                df_nse_indices.to_excel(
                    writer, sheet_name="All NSE Indices", index=False
                )

            if not df_summary.empty:
                df_summary.to_excel(
                    writer, sheet_name="Index Summary", index=False
                )

            if not df_valid.empty:
                df_valid.to_excel(
                    writer, sheet_name="All Mapped Funds", index=False
                )

            if not df_nse_ranked.empty:
                df_nse_ranked.to_excel(
                    writer, sheet_name="ETFs by Liquidity", index=False
                )

            if not df_benchmarks.empty:
                df_benchmarks.to_excel(
                    writer, sheet_name="Benchmark Codes", index=False
                )

            # Summary stats sheet
            stats = {
                "Metric": [
                    "Total NSE Indices",
                    "Total NSE ETFs Listed",
                    "Total AMFI ETF/Index Schemes",
                    "Unique Indices with Products",
                    "Total Benchmark Codes",
                    "Data Fetched On",
                ],
                "Value": [
                    len(df_nse_indices) if not df_nse_indices.empty else 0,
                    len(nse_funds) if not nse_funds.empty else 0,
                    len(amfi_funds) if not amfi_funds.empty else 0,
                    len(df_summary) if not df_summary.empty else 0,
                    len(df_benchmarks) if not df_benchmarks.empty else 0,
                    datetime.now().strftime("%Y-%m-%d %H:%M"),
                ],
            }
            pd.DataFrame(stats).to_excel(
                writer, sheet_name="Summary", index=False
            )

        log.info(f"  → Final spreadsheet saved to {outpath}")
    except ImportError:
        log.warning("  openpyxl not available, saving as CSV instead")
        outpath = DATA_DIR / "07_final_shortlist.csv"
        df_summary.to_csv(outpath, index=False)
        log.info(f"  → Saved summary to {outpath}")

    return df_summary


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 70)
    log.info("ETF & Index Fund Data Automation - Starting")
    log.info("=" * 70)

    session = get_session()

    # Step 1: NSE Indices
    df_indices = fetch_nse_indices(session)

    # Step 2: NSE ETFs
    df_etfs = fetch_nse_etfs(session)

    # Step 3: AMFI Schemes
    df_amfi = fetch_amfi_schemes(session)

    # Step 4: Benchmark Codes
    df_benchmarks = fetch_benchmark_codes(session)

    # Step 5: mfapi catalog (supplementary)
    df_mfapi = fetch_mfapi_catalog(session)

    # Step 6: Map funds to indices
    df_mapped = map_funds_to_indices(df_amfi, df_etfs, df_indices)

    # Step 7: Build final spreadsheet
    df_summary = build_final_shortlist(df_mapped, df_indices, df_benchmarks)

    # Print summary
    log.info("")
    log.info("=" * 70)
    log.info("SUMMARY")
    log.info("=" * 70)
    if not df_summary.empty:
        log.info(f"Indices with passive products: {len(df_summary)}")
        log.info(f"\nTop 20 indices by number of products:")
        top20 = df_summary.head(20)
        for _, row in top20.iterrows():
            log.info(
                f"  {row['Index_Name']:50s} | "
                f"Products: {row['Total_Products']:3d} | "
                f"Category: {row.get('Category', 'N/A')}"
            )
    log.info("")
    log.info(f"All output files in: {DATA_DIR.resolve()}")
    log.info("=" * 70)
    log.info("Done!")


if __name__ == "__main__":
    main()
