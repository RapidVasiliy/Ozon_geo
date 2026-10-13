import importlib.util
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("run_ozon_geo", Path(__file__).resolve().parents[1] / "run_ozon_geo.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def test_load_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('\ufeff# комментарий\nOZON_CLIENT_ID=123\nOZON_API_KEY="abc-def"\n\nбез_равно\nX_OTHER = \'v\'\n', encoding="utf-8")
    for k in ("OZON_CLIENT_ID", "OZON_API_KEY", "X_OTHER"):
        monkeypatch.delenv(k, raising=False)
    run.load_dotenv(tmp_path / "нет_такого", env)
    assert os.environ["OZON_CLIENT_ID"] == "123" and os.environ["OZON_API_KEY"] == "abc-def" and os.environ["X_OTHER"] == "v"
    monkeypatch.setenv("OZON_CLIENT_ID", "из_окружения")
    run.load_dotenv(env)  # уже заданные переменные не перезаписываются
    assert os.environ["OZON_CLIENT_ID"] == "из_окружения"
    monkeypatch.delenv("OZON_API_KEY"); monkeypatch.delenv("X_OTHER"); monkeypatch.delenv("OZON_CLIENT_ID")
