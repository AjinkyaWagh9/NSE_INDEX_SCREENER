# PyInstaller spec. Build from the repo root:  pyinstaller --noconfirm screener/NSEScreener.spec
# Requires screener/secrets_local.py to exist (its API key is bundled into the executable).
from pathlib import Path

root = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller

a = Analysis(
    [str(root / "screener" / "desktop" / "app.py")],
    pathex=[str(root)],
    datas=[(str(root / "screener" / "core" / "universe.json"), "screener/core")],
    hiddenimports=["screener.secrets_local", "autobahn.twisted.websocket", "twisted.internet.reactor"],
    # The app needs only PySide6, kiteconnect and requests. Keep data-science / ML packages
    # out even if they happen to be installed in the build environment.
    excludes=["pandas", "numpy", "openpyxl", "pyarrow", "scipy", "sympy", "sklearn", "nltk",
              "networkx", "torch", "torchvision", "transformers", "huggingface_hub", "botocore",
              "boto3", "cv2", "PIL", "pygame", "matplotlib", "tkinter", "IPython", "pygments",
              "rich", "pydantic", "mcp", "ranking", "build_presentation"],
)
pyz = PYZ(a.pure)
# Passing binaries + datas straight to EXE (no COLLECT step) produces a one-file build.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="NSEScreener",
          console=False, upx=False)
