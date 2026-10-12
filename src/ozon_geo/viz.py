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


# --- помесячные графики: SKU × кластер ----------------------------------------------------------
def sku_family(name: str) -> str:
    """Семейство товара по началу названия: до первой цифры, кавычки или скобки."""
    import re

    fam = re.split(r"[\d\"«(,]", str(name))[0].strip(" -–.")
    return fam or "Прочее"


def short_name(name: str, n: int = 34) -> str:
    """Отличительная часть названия: текст в кавычках («Полоски бордовые»), иначе начало названия."""
    import re

    m = re.search(r'"([^"]+)"', str(name))
    return (m.group(1) if m else str(name))[:n]


def _month_labels(df: pd.DataFrame, months: list[str]) -> list[str]:
    last = df["created_at"].max()
    labels = list(months)
    # последний месяц неполный, если данные кончаются до его конца
    if last.is_month_end is False and last.strftime("%Y-%m") == months[-1]:
        labels[-1] = f"{months[-1]}\n(до {last:%d.%m})"
    return labels


def _shades(base, n: int):
    import matplotlib.colors as mc

    r, g, b = mc.to_rgb(base)
    return [tuple(c + (1 - c) * 0.6 * (k / max(n - 1, 1)) for c in (r, g, b)) for k in range(n)]


def _sku_colors(df: pd.DataFrame, metric: str, max_families: int = 5):
    """Порядок SKU и цвета: цвет — семейство, оттенок — позиция SKU в семействе (по убыванию продаж)."""
    import matplotlib.pyplot as plt

    names = df.groupby("sku")["name"].first()
    fam = names.map(sku_family)
    tot = df.groupby("sku")[metric].sum()
    keep = tot.groupby(fam).sum().sort_values(ascending=False).index[:max_families]
    fam = fam.where(fam.isin(keep), "Прочее")  # мелкие семейства сливаются, чтобы легенда читалась
    fam_tot = tot.groupby(fam).sum().sort_values(ascending=False)
    base = plt.get_cmap("tab10").colors
    colors, order = {}, []
    for k, f in enumerate(fam_tot.index):
        skus = tot[fam[fam == f].index].sort_values(ascending=False).index.tolist()
        for s, c in zip(skus, _shades(base[k % 10], len(skus))):
            colors[s] = c
        order += skus
    return order, colors, fam, fam_tot, {f: base[k % 10] for k, f in enumerate(fam_tot.index)}


def monthly_sku_by_cluster(df: pd.DataFrame, metric: str = "quantity", top_clusters: int = 7, geo: str = "cluster"):
    """Столбики по месяцам, у каждого сегмент = один SKU. По панели на кластер (остальные — в одну).

    Цвет сегмента — семейство товара, оттенок — конкретный SKU внутри семейства; границы белые, поэтому
    каждый SKU виден отдельным куском столбика, даже когда их десятки.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    d = df.copy()
    d["month"] = d["created_at"].dt.strftime("%Y-%m")
    months = sorted(d["month"].unique())
    col = analytics.GEOS[geo]
    top = d.groupby(col)[metric].sum().sort_values(ascending=False).index[:top_clusters].tolist()
    d["panel"] = d[col].where(d[col].isin(top), "Остальные")
    panels = top + (["Остальные"] if (d["panel"] == "Остальные").any() else [])
    order, colors, fam, fam_tot, fam_color = _sku_colors(d, metric)
    labels = _month_labels(d, months)

    ncols = 4
    nrows = -(-len(panels) // ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.2 * ncols, 3.6 * nrows + 1.2), squeeze=False)
    for ax, panel in zip(axes.ravel(), panels):
        sub = d[d["panel"] == panel]
        pv = sub.pivot_table(index="month", columns="sku", values=metric, aggfunc="sum", fill_value=0)
        pv = pv.reindex(index=months, fill_value=0).reindex(columns=order, fill_value=0)
        bottom = pd.Series(0.0, index=months)
        for sku in order:
            v = pv[sku]
            if v.any():
                ax.bar(range(len(months)), v.values, bottom=bottom.values, color=colors[sku],
                       edgecolor="white", linewidth=0.3, width=0.8)
                bottom += v
        ax.set_xticks(range(len(months)), labels, fontsize=8)
        ax.set_title(f"{panel} — {sub[metric].sum():,.0f}", fontsize=10)
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
    for ax in axes.ravel()[len(panels):]:
        ax.axis("off")
    handles = [Patch(color=fam_color[f], label=f"{f} ({fam.eq(f).sum()} SKU, {fam_tot[f]:,.0f})") for f in fam_tot.index]
    fig.legend(handles=handles, loc="lower center", ncol=min(len(handles), 3), frameon=False, fontsize=9,
               title="Семейство товара (оттенок внутри — отдельный SKU)")
    fig.suptitle(f"{metric} по месяцам: SKU × {geo}", fontsize=13)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    return fig


def monthly_sku_heatmap(df: pd.DataFrame, metric: str = "quantity"):
    """Все SKU × месяцы: строка — SKU, столбец — месяц, число в клетке — метрика."""
    import matplotlib.pyplot as plt

    d = df.copy()
    d["month"] = d["created_at"].dt.strftime("%Y-%m")
    months = sorted(d["month"].unique())
    order, _, fam, _, fam_color = _sku_colors(d, metric)
    pv = d.pivot_table(index="sku", columns="month", values=metric, aggfunc="sum", fill_value=0)
    pv = pv.reindex(index=order, columns=months, fill_value=0)
    names = d.groupby("sku")["name"].first()
    fig, ax = plt.subplots(figsize=(max(7, 1.1 * len(months) + 5), max(4, 0.24 * len(order) + 1.5)))
    share = pv.div(pv.max(axis=1).replace(0, 1), axis=0)  # цвет — относительно максимума SKU: видна форма сезона
    ax.imshow(share.values, aspect="auto", cmap="YlOrRd", vmin=0, vmax=1.15)
    ax.set_xticks(range(len(months)), _month_labels(d, months), fontsize=8)
    ax.set_yticks(range(len(order)), [f"{s}  {short_name(names[s])}" for s in order], fontsize=7)
    for tick, s in zip(ax.get_yticklabels(), order):
        tick.set_color(fam_color[fam[s]])
    for i in range(pv.shape[0]):
        for j in range(pv.shape[1]):
            if pv.iat[i, j]:
                ax.text(j, i, f"{pv.iat[i, j]:.0f}", ha="center", va="center", fontsize=6.5,
                        color="white" if share.iat[i, j] > 0.6 else "black")
    ax.set_title(f"{metric}: все SKU × месяцы (цвет — доля от максимума SKU, цвет подписи — семейство)", fontsize=10)
    fig.tight_layout()
    return fig
