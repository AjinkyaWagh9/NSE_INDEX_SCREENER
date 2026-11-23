#!/usr/bin/env python3
"""Entry point to launch the NSE Index Screener desktop app.

Usage:
    python3 main.py
    ./main.py
"""
import sys
from screener.desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
