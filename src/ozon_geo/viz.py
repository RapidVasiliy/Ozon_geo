"""Графики и сводки для ноутбука (matplotlib импортируется лениво)."""
from __future__ import annotations

import pandas as pd

from . import analytics, forecast


def heatmap(df: pd.DataFrame, level: str = "sku", geo: str = "cluster", metric: str = "quantity",
            rows: int = 25, cols: int = 15, min_total: int = 1):
    """Тепловая карта: цвет — доля направления в продажах строки (SKU/категории), подпись — значение метрики.

    Показаны `rows` самых продаваемых строк и `cols` самых крупных направлений.
    """
    import matplotlib.pyplot as plt

    m = analytics.matrix(df, level, metric, geo=geo)
    m = m[m.sum(axis=1) >= min_total].iloc[:rows, :cols]
    if m.empty:
        raise ValueError("Нет данных для карты (проверьте период и фильтры)")
    share = m.div(m.sum(axis=1).replace(0, 1), axis=0)
    names = _labels(df, level, list(m.index))
    fig, ax = plt.subplots(figsize=(max(8, 0.9 * m.shape[1] + 4), max(4, 0.38 * m.shape[0] + 2)))
    im = ax.imshow(share.values, aspect="auto", cmap="YlGnBu", vmin=0, vmax=max(share.values.max(), 0.01))
    ax.set_xticks(range(m.shape[1]), m.columns, rotation=45, ha="right")
    ax.set_yticks(range(m.shape[0]), names)
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m.iat[i, j]
            if v:
                ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if share.iat[i, j] > 0.5 * share.values.max() else "black")
    fig.colorbar(im, ax=ax, label="доля направления в продажах строки")
    ax.set_title(f"{metric}: {level} × {geo}")
    fig.tight_layout()
    return fig


def _labels(df: pd.DataFrame, level: str, keys: list[str]) -> list[str]:
    if level in ("sku", "offer"):
        names = df.groupby(analytics.LEVELS[level])["name"].first()
        return [f"{k} {str(names.get(k, ''))[:30]}" for k in keys]
    return [str(k)[:40] for k in keys]


def weekly_totals(df: pd.DataFrame):
    """Линия: штуки в неделю по всему магазину (последняя, неполная неделя не показывается)."""
    import matplotlib.pyplot as plt

    p = analytics.weekly_panel(df, "category", "cluster").groupby("week")["quantity"].sum().iloc[:-1]
    fig, ax = plt.subplots(figsize=(10, 3.5))
    p.plot(ax=ax, marker="o")
    ax.set_ylabel("штук в неделю")
    ax.set_title("Динамика продаж")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def restock_plan(df: pd.DataFrame, level: str = "sku", geo: str = "cluster", horizon: int = 4,
                 window: int = 4) -> pd.DataFrame:
    """Базовая потребность на `horizon` недель вперёд = среднее за последние `window` недель × horizon.

    Это бейзлайн для разговора, а не прогноз: на малой истории ему нельзя верить на уровне SKU×кластер.
    Последняя неделя может быть неполной, поэтому она исключается.
    """
    panel = analytics.weekly_panel(df, level, geo)
    panel = panel[panel["week"] < panel["week"].max()]
    pred = forecast.MovingAverage(window).fit(panel).predict(horizon)
    out = pred.groupby(["category", "destination"], as_index=False)["forecast"].sum()
    out = out.rename(columns={"category": level, "forecast": f"нужно_шт_на_{horizon}_нед"})
    out[out.columns[-1]] = out[out.columns[-1]].round(1)
    return out.sort_values(out.columns[-1], ascending=False).reset_index(drop=True)


def export_excel(path: str, df: pd.DataFrame, level: str, geo: str, horizon: int = 4) -> str:
    """Один xlsx: детально, матрица, топ направлений, план потребности."""
    with pd.ExcelWriter(path) as w:
        analytics.category_city(df, level, geo).to_excel(w, sheet_name="детально", index=False)
        analytics.matrix(df, level, "quantity", geo=geo).to_excel(w, sheet_name="матрица_шт")
        analytics.matrix(df, level, "revenue", geo=geo).round(0).to_excel(w, sheet_name="матрица_выручка")
        analytics.top_cities(df, level, 5, "quantity", geo).to_excel(w, sheet_name="топ_направлений", index=False)
        restock_plan(df, level, geo, horizon).to_excel(w, sheet_name="план_потребности", index=False)
    return path
