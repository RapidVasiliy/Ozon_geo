"""Агрегации «категория × город»."""
from __future__ import annotations

import pandas as pd

LEVELS = {"category": "category", "type": "product_type"}
METRICS = ("quantity", "orders", "revenue")
# куда уехал товар: город доставки или кластер Ozon (по нему планируются остатки FBO)
GEOS = {"city": "city", "cluster": "cluster"}


def prepare(df: pd.DataFrame, include_cancelled: bool = False, since=None, to=None) -> pd.DataFrame:
    out = df
    if not include_cancelled:
        out = out[out["status"] != "cancelled"]
    if since is not None:
        out = out[out["created_at"] >= pd.Timestamp(since, tz="UTC")]
    if to is not None:
        out = out[out["created_at"] < pd.Timestamp(to, tz="UTC")]
    return out.copy()


def category_city(df: pd.DataFrame, level: str = "category", geo: str = "city") -> pd.DataFrame:
    """Длинная таблица: категория, город, штуки, заказы, выручка + доли и lift.

    destination — город или кластер доставки (параметр geo);
    share_in_category — какая доля продаж категории ушла в это направление;
    lift — во сколько раз эта доля выше, чем доля направления во всех продажах
    (>1: город «любит» категорию сильнее среднего).
    """
    col, gcol = LEVELS[level], GEOS[geo]
    g = (df.groupby([col, gcol])
           .agg(quantity=("quantity", "sum"), orders=("posting_number", "nunique"),
                revenue=("revenue", "sum"))
           .reset_index().rename(columns={col: "category", gcol: "destination"}))
    cat_total = g.groupby("category")["quantity"].transform("sum")
    city_share = g.groupby("destination")["quantity"].transform("sum") / g["quantity"].sum()
    g["share_in_category"] = g["quantity"] / cat_total
    g["lift"] = g["share_in_category"] / city_share
    return g.sort_values(["category", "quantity"], ascending=[True, False]).reset_index(drop=True)


def matrix(df: pd.DataFrame, level: str = "category", metric: str = "quantity",
           top_cities: int | None = None, geo: str = "city") -> pd.DataFrame:
    """Сводная таблица: строки — категории, столбцы — города."""
    g = category_city(df, level, geo)
    pv = g.pivot_table(index="category", columns="destination", values=metric, aggfunc="sum", fill_value=0)
    pv = pv.loc[pv.sum(axis=1).sort_values(ascending=False).index]
    pv = pv[pv.sum(axis=0).sort_values(ascending=False).index]
    return pv.iloc[:, :top_cities] if top_cities else pv


def top_cities(df: pd.DataFrame, level: str = "category", n: int = 5, metric: str = "quantity",
               geo: str = "city") -> pd.DataFrame:
    g = category_city(df, level, geo)
    g["rank"] = g.groupby("category")[metric].rank(method="first", ascending=False)
    return g[g["rank"] <= n].sort_values(["category", "rank"]).reset_index(drop=True)


def weekly_panel(df: pd.DataFrame, level: str = "category", geo: str = "city") -> pd.DataFrame:
    """Панель category × city × неделя (пропущенные недели заполнены нулями).

    Это входные данные для будущей предиктивной модели.
    """
    col, gcol = LEVELS[level], GEOS[geo]
    d = df.dropna(subset=["created_at"]).copy()
    d["week"] = d["created_at"].dt.tz_convert(None).dt.to_period("W-SUN").dt.start_time
    g = (d.groupby([col, gcol, "week"])
           .agg(quantity=("quantity", "sum"), revenue=("revenue", "sum")).reset_index()
           .rename(columns={col: "category", gcol: "destination"}))
    weeks = pd.date_range(g["week"].min(), g["week"].max(), freq="W-MON")
    parts = []
    for (cat, city), sub in g.groupby(["category", "destination"]):
        s = sub.set_index("week")[["quantity", "revenue"]].reindex(weeks, fill_value=0)
        s.index.name = "week"
        s = s.reset_index()
        s.insert(0, "destination", city)
        s.insert(0, "category", cat)
        parts.append(s)
    return pd.concat(parts, ignore_index=True) if parts else g
