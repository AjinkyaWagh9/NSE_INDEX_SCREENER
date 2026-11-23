#!/usr/bin/env python3
"""Start the NSE Index Screener Web Server:

    python3 run_web.py
    ./run_web.py

Open in your browser at:
    http://localhost:8000
"""
import uvicorn

if __name__ == "__main__":
    print("\n=======================================================")
    print("  NSE Index Screener Web Server")
    print("  Local URL:   http://localhost:8000")
    print("  Network URL: http://0.0.0.0:8000")
    print("=======================================================\n")
    uvicorn.run("web.server:app", host="0.0.0.0", port=8000, reload=False)
