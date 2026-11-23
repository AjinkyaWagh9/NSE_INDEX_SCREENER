import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # Qt tests run headless

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolate_screener_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREENER_DATA_DIR", str(tmp_path))
