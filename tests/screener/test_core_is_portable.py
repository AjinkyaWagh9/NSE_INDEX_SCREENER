"""screener/core must stay free of Qt and desktop code so it can move to the web app."""
import subprocess
import sys

CORE = ["config", "returns", "db", "universe", "amfi_client", "kite_client", "service"]


def test_core_imports_no_qt_or_desktop():
    code = ("import sys\n"
            + "".join(f"import screener.core.{m}\n" for m in CORE)
            + "bad = [m for m in sys.modules if m.startswith(('PySide6', 'screener.desktop'))]\n"
            + "assert not bad, bad\n")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
