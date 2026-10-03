"""CLI: ozon-geo sync | demo | report | forecast"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import analytics, forecast
from .client import OzonClient
from .store import Store
from .sync import sync


def _date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _cmd_sync(a, store: Store) -> None:
    to = _date(a.to) if a.to else datetime.now(timezone.utc)
    since = _date(a.since) if a.since else to - timedelta(days=a.days)
    sync(OzonClient(), store, since, to, tuple(a.schemes))


def _cmd_demo(a, store: Store) -> None:
    from .demo import generate
    print(f"Сгенерировано отправлений: {generate(store, days=a.days, seed=a.seed)}")


def _cmd_report(a, store: Store) -> None:
    df = analytics.prepare(store.sales_frame(), a.include_cancelled, a.since, a.to)
    if df.empty:
        raise SystemExit("Нет данных. Сначала выполните `ozon-geo sync` (или `demo`).")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    long = analytics.category_city(df, a.level)
    long.to_csv(out / "category_city.csv", index=False)
    mat = analytics.matrix(df, a.level, a.metric)
    mat.to_csv(out / f"matrix_{a.metric}.csv")
    top = analytics.top_cities(df, a.level, a.top, a.metric)
    top.to_csv(out / "top_cities_per_category.csv", index=False)
    analytics.weekly_panel(df, a.level).to_csv(out / "weekly_panel.csv", index=False)
    pd.set_option("display.width", 200, "display.max_columns", 20)
    print(top[["category", "city", "quantity", "orders", "revenue", "share_in_category", "lift"]]
          .round(2).to_string(index=False))
    print(f"\nФайлы сохранены в {out}/")


def _cmd_forecast(a, store: Store) -> None:
    df = analytics.prepare(store.sales_frame(), False)
    panel = analytics.weekly_panel(df, a.level)
    for name, model in (("moving_average", forecast.MovingAverage(4)),
                        ("seasonal_naive", forecast.SeasonalNaive(52))):
        print(name, forecast.backtest(panel, model, a.horizon))
    pred = forecast.MovingAverage(4).fit(panel).predict(a.horizon)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    pred.to_csv(Path(a.out) / "forecast.csv", index=False)
    print(f"Прогноз на {a.horizon} нед. -> {a.out}/forecast.csv")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="ozon-geo")
    ap.add_argument("--db", default="ozon.db")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="загрузить отправления из Ozon API")
    s.add_argument("--days", type=int, default=90)
    s.add_argument("--since"), s.add_argument("--to")
    s.add_argument("--schemes", nargs="+", default=["fbs", "fbo"], choices=["fbs", "fbo"])
    s.set_defaults(fn=_cmd_sync)

    d = sub.add_parser("demo", help="сгенерировать демо-данные")
    d.add_argument("--days", type=int, default=365), d.add_argument("--seed", type=int, default=0)
    d.set_defaults(fn=_cmd_demo)

    r = sub.add_parser("report", help="категория × город")
    r.add_argument("--level", choices=list(analytics.LEVELS), default="category")
    r.add_argument("--metric", choices=analytics.METRICS, default="quantity")
    r.add_argument("--top", type=int, default=3)
    r.add_argument("--since"), r.add_argument("--to")
    r.add_argument("--include-cancelled", action="store_true")
    r.add_argument("--out", default="out")
    r.set_defaults(fn=_cmd_report)

    f = sub.add_parser("forecast", help="бейзлайн-прогноз спроса по неделям")
    f.add_argument("--level", choices=list(analytics.LEVELS), default="category")
    f.add_argument("--horizon", type=int, default=4)
    f.add_argument("--out", default="out")
    f.set_defaults(fn=_cmd_forecast)

    a = ap.parse_args(argv)
    store = Store(a.db)
    try:
        a.fn(a, store)
    finally:
        store.close()


if __name__ == "__main__":
    main()
