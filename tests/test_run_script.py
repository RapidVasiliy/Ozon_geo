import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args, stdin=None):
    return subprocess.run([sys.executable, str(ROOT / "run_ozon_geo.py"), *args], capture_output=True, text=True,
                          encoding="utf-8", stdin=stdin, timeout=240)


def test_demo_run_creates_outputs(tmp_path):
    r = _run("--source", "demo", "--db", str(tmp_path / "d.db"), "--out", str(tmp_path / "out"), "--no-charts")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "out" / "clusters_by_month.xlsx").exists()
    assert (tmp_path / "out" / "ozon_geo.xlsx").exists()
    assert "По месяцам" in r.stdout


def test_empty_db_and_missing_keys_exit_cleanly(tmp_path, monkeypatch):
    r = _run("--source", "db", "--db", str(tmp_path / "empty.db"), "--out", str(tmp_path / "o"))
    assert r.returncode != 0 and "нет данных" in (r.stdout + r.stderr)
    monkeypatch.delenv("OZON_CLIENT_ID", raising=False)
    monkeypatch.delenv("OZON_API_KEY", raising=False)
    r = _run("--source", "api", "--db", str(tmp_path / "a.db"), stdin=subprocess.DEVNULL)
    assert r.returncode != 0 and "Ключи не заданы" in (r.stdout + r.stderr) and "Traceback" not in r.stderr
