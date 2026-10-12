import json
import os
from pathlib import Path

import pytest

NB = Path(__file__).resolve().parents[1] / "ozon_geo.ipynb"


def test_notebook_is_valid_and_code_compiles():
    nb = json.loads(NB.read_text(encoding="utf-8"))
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code) >= 6
    for c in code:
        src = "".join(line for line in c["source"] if not line.lstrip().startswith("%"))
        compile(src, "<cell>", "exec")


@pytest.mark.skipif(not os.environ.get("OZON_GEO_TEST_NB"), reason="долго: OZON_GEO_TEST_NB=1 для полного прогона")
def test_notebook_runs_on_demo(tmp_path, monkeypatch):
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("matplotlib")
    pytest.importorskip("ipywidgets")
    monkeypatch.setenv("OZON_GEO_SOURCE", "demo")
    nb = nbformat.read(NB, 4)
    nbclient.NotebookClient(nb, timeout=300, kernel_name="python3",
                            resources={"metadata": {"path": str(tmp_path)}}).execute()
    assert (tmp_path / "out" / "ozon_geo.xlsx").exists()
