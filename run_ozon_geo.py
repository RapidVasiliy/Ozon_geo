#!/usr/bin/env python3
"""Запуск ozon-geo одним файлом (то же, что ноутбук ozon_geo.ipynb, но без Jupyter).

Что делает: загружает отправления FBS -> считает «кластер × SKU × месяц» -> сохраняет таблицы и графики в out/.

Примеры (из папки с этим файлом):
    python run_ozon_geo.py                                  # API, с 2022-01-01 до сегодня
    python run_ozon_geo.py --since 2023-10-01 --to 2024-10-01
    python run_ozon_geo.py --source csv --csv "orders/*.csv"  # выгрузки из кабинета
    python run_ozon_geo.py --source db                        # без загрузки: пересобрать отчёты из ozon.db
    python run_ozon_geo.py --source demo                      # демо-данные, ключи не нужны

Ключи API (роль «Только чтение») берутся из переменных OZON_CLIENT_ID / OZON_API_KEY или запрашиваются
при запуске (ключ вводится скрытно и нигде не сохраняется).

Нужно один раз:  pip install pandas requests openpyxl matplotlib
"""
from __future__ import annotations

import argparse
import getpass
import glob
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))  # работает и без `pip install -e .`
try:
    sys.stdout.reconfigure(encoding="utf-8")  # кириллица в консоли Windows
except Exception:  # noqa: BLE001
    pass

# ======================= НАСТРОЙКИ (можно менять здесь или аргументами командной строки) ===============
SOURCE = "api"            # api | csv | db | demo
SINCE = "2022-01-01"      # начало периода для api (ГГГГ-ММ-ДД); окна без заказов проходятся быстро
TO = None                 # конец периода для api; None — сегодня
SCHEMES = "fbs"           # fbs | "fbs fbo"
CSV_FILES = "orders/*.csv"  # маски файлов для source=csv, через запятую
DB_PATH = "ozon.db"       # локальная база (SQLite); повторные запуски дополняют её
OUT_DIR = "out"
ONLY_DELIVERED = False    # True — считать только доставленные
GEO = "cluster"           # cluster (кластер доставки) | city
LEVEL = "sku"             # sku | offer | category | type  (для графиков и сводного Excel)
METRIC = "quantity"       # quantity | revenue
# =====================================================================================================


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="ozon-geo: загрузка FBS и отчёты кластер × SKU × месяц")
    ap.add_argument("--source", choices=["api", "csv", "db", "demo"], default=SOURCE)
    ap.add_argument("--since", default=SINCE)
    ap.add_argument("--to", default=TO)
    ap.add_argument("--schemes", default=SCHEMES, help='"fbs" или "fbs fbo"')
    ap.add_argument("--csv", default=CSV_FILES)
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--only-delivered", action="store_true", default=ONLY_DELIVERED)
    ap.add_argument("--geo", choices=["cluster", "city"], default=GEO)
    ap.add_argument("--level", choices=["sku", "offer", "category", "type"], default=LEVEL)
    ap.add_argument("--metric", choices=["quantity", "revenue"], default=METRIC)
    ap.add_argument("--no-charts", action="store_true", help="не рисовать графики (быстрее, не нужен matplotlib)")
    return ap.parse_args()


def day(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def load(a: argparse.Namespace, store) -> None:
    if a.source == "db":
        print(f"Загрузка пропущена: используется база {a.db}")
    elif a.source == "demo":
        from ozon_geo.demo import generate
        print(f"Демо-данные: {generate(store, days=365)} отправлений")
    elif a.source == "csv":
        from ozon_geo.importer import import_postings_files
        files = sorted({f for mask in a.csv.split(",") for f in glob.glob(mask.strip())})
        if not files:
            sys.exit(f"Не найдено файлов по маске {a.csv!r}. Положите выгрузки из кабинета в папку orders/.")
        print("Файлы:", *files, sep="\n  ")
        import_postings_files(store, files)
    else:
        from ozon_geo.client import OzonClient, OzonError
        from ozon_geo.sync import sync

        try:
            cid = os.environ.get("OZON_CLIENT_ID") or input("Client-Id: ").strip()
            key = os.environ.get("OZON_API_KEY") or getpass.getpass("Api-Key (ввод скрыт): ").strip()
        except EOFError:
            sys.exit("Ключи не заданы: укажите переменные OZON_CLIENT_ID и OZON_API_KEY или запустите скрипт в обычном окне терминала.")
        if not cid or not key:
            sys.exit("Нужны и Client-Id, и Api-Key.")
        to = day(a.to) if a.to else datetime.now(timezone.utc)
        since = day(a.since)
        print(f"Загрузка из Ozon API: {since:%Y-%m-%d} → {to:%Y-%m-%d}, схемы: {a.schemes}")
        try:
            counts = sync(OzonClient(cid, key), store, since, to, tuple(a.schemes.split()))
        except OzonError as e:
            hint = ""
            if "403" in str(e):
                hint = "\nПроверьте Client-Id/Api-Key и что у ключа есть доступ к заказам."
            elif "400" in str(e):
                hint = "\nПохоже на ошибку формата запроса: пришлите текст ошибки целиком (ключи в нём не видны)."
            sys.exit(f"Ошибка API: {e}{hint}")
        if not any(counts.values()):
            print("⚠ За этот период отправлений нет.")


def main() -> None:
    a = parse_args()
    try:
        import pandas as pd
        from ozon_geo import analytics
        from ozon_geo.store import Store
    except ImportError as e:  # noqa: BLE001
        sys.exit(f"Не хватает пакета: {e}\nУстановите: pip install pandas requests openpyxl matplotlib")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    store = Store(a.db)
    load(a, store)

    sales = store.sales_frame()
    if sales.empty:
        sys.exit("В базе нет данных. Проверьте источник и период.")
    df = analytics.prepare(sales, False, only_delivered=a.only_delivered)

    first, last = sales["created_at"].min(), sales["created_at"].max()
    print(f"\nВ базе: {sales.posting_number.nunique():,} отправлений, {sales.sku.nunique()} SKU, "
          f"период {first:%Y-%m-%d} → {last:%Y-%m-%d} (московское время)")
    print(f"Без города: {(sales.city == '(не определён)').mean():.1%}; без кластера: {(sales.cluster == '(не определён)').mean():.1%}")
    by_month = df.assign(месяц=df.created_at.dt.strftime("%Y-%m")).groupby("месяц").agg(
        отправлений=("posting_number", "nunique"), штук=("quantity", "sum"), выручка=("revenue", "sum")).round(0)
    print("\nПо месяцам (без отменённых):")
    print(by_month.to_string())
    if (last - first).days < 360:
        print("\n⚠ История короче года: сезонность не видна, прогнозам верьте осторожно.")

    # --- таблицы ---
    from ozon_geo.xlsx_report import cluster_month_workbook
    from ozon_geo import viz
    p1 = cluster_month_workbook(df, str(out / "clusters_by_month.xlsx"), a.metric, a.geo)
    print(f"\nСохранено: {p1}   (вкладка = кластер, строки = SKU, столбцы = месяцы)")
    try:
        p2 = viz.export_excel(str(out / "ozon_geo.xlsx"), df, a.level, a.geo, 4)
        print(f"Сохранено: {p2}   (детально, матрицы, топ направлений, базовая потребность)")
    except Exception as e:  # noqa: BLE001
        print(f"Сводный Excel не собран: {e}")

    # --- графики ---
    if not a.no_charts:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("Графики пропущены: нет matplotlib (pip install matplotlib)")
        else:
            charts = {
                "monthly_sku_by_cluster": lambda: viz.monthly_sku_by_cluster(df, a.metric, 7, a.geo),
                "monthly_sku_heatmap": lambda: viz.monthly_sku_heatmap(df, a.metric),
                "heatmap_sku_cluster": lambda: viz.heatmap(df, a.level, a.geo, a.metric, 25, 15),
                "weekly_totals": lambda: viz.weekly_totals(df),
            }
            for name, make in charts.items():
                try:
                    fig = make()
                    viz.save_png_pdf(fig, str(out / name), 150)
                    plt.close(fig)
                    print(f"Сохранено: {out / name}.png / .pdf")
                except Exception as e:  # noqa: BLE001
                    print(f"График {name} не построен: {e}")
    print(f"\nГотово. Результаты в папке {out.resolve()}. База: {Path(a.db).resolve()}")


if __name__ == "__main__":
    main()
