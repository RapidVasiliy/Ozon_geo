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
        names = analytics.latest_names(df, analytics.LEVELS[level])
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
# Тип товара по ключевым словам названия (порядок важен: первое совпавшее правило побеждает).
# «Прочее» — всё, что не подошло. Правила под ассортимент магазина; для другого ассортимента дополните список.
FAMILY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Компрессная бумага", ("компрессная",)),
    ("Подпергамент", ("подпергамент",)),
    ("Восковые салфетки", ("салфет",)),
    ("Парафинированная / вощёная", ("парафин", "воще", "восков", "воск ")),
    ("Бумага для выпечки", ("силикон", "для выпеч", "для выпек", "пергамент")),
]


def sku_family(name: str) -> str:
    """Семейство (тип) товара по ключевым словам в названии; не подошло ни одно правило — «Прочее»."""
    low = str(name).lower() + " "
    for family, words in FAMILY_RULES:
        if any(w in low for w in words):
            return family
    return "Прочее"


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


def _thin_ticks(ax, labels: list[str], max_labels: int = 14) -> None:
    """Подписи месяцев на оси X: при длинной истории показываем каждую N-ю и поворачиваем."""
    n = len(labels)
    step = max(1, -(-n // max_labels))
    idx = list(range(0, n, step))
    ax.set_xticks(idx, [labels[i].replace("\n", " ") if step > 1 else labels[i] for i in idx],
                  fontsize=8, rotation=45 if step > 1 else 0, ha="right" if step > 1 else "center")


def _shades(base, n: int):
    import matplotlib.colors as mc

    r, g, b = mc.to_rgb(base)
    return [tuple(c + (1 - c) * 0.6 * (k / max(n - 1, 1)) for c in (r, g, b)) for k in range(n)]


def _sku_colors(df: pd.DataFrame, metric: str, max_families: int = 6):
    """Порядок SKU и цвета: цвет — семейство, оттенок — позиция SKU в семействе (по убыванию продаж)."""
    import matplotlib.pyplot as plt

    names = analytics.latest_names(df, "sku")
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
                       edgecolor="white", linewidth=0.3 if len(months) <= 24 else 0.1, width=0.85)
                bottom += v
        _thin_ticks(ax, labels, 8 if len(months) > 14 else 99)
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
    names = analytics.latest_names(d, "sku")
    annotate = len(months) <= 24
    fig, ax = plt.subplots(figsize=(min(26, max(7, (1.1 if annotate else 0.32) * len(months) + 6)), max(4, 0.24 * len(order) + 1.5)))
    share = pv.div(pv.max(axis=1).replace(0, 1), axis=0)  # цвет — относительно максимума SKU: видна форма сезона
    ax.imshow(share.values, aspect="auto", cmap="YlOrRd", vmin=0, vmax=1.15)
    _thin_ticks(ax, _month_labels(d, months), 24)
    ax.set_yticks(range(len(order)), [f"{s}  {short_name(names[s])}" for s in order], fontsize=7)
    for tick, s in zip(ax.get_yticklabels(), order):
        tick.set_color(fam_color[fam[s]])
    for i in range(pv.shape[0] if annotate else 0):
        for j in range(pv.shape[1]):
            if pv.iat[i, j]:
                ax.text(j, i, f"{pv.iat[i, j]:.0f}", ha="center", va="center", fontsize=6.5,
                        color="white" if share.iat[i, j] > 0.6 else "black")
    ax.set_title(f"{metric}: все SKU × месяцы (цвет — доля от максимума SKU, цвет подписи — семейство)", fontsize=10)
    fig.tight_layout()
    return fig


def cluster_month_bars(df: pd.DataFrame, cluster: str, month: str, metric: str = "quantity", geo: str = "cluster",
                       max_families: int = 6):
    """Один кластер, один месяц: столбики SKU по убыванию продаж (слева самые популярные), подписи — SKU и название.

    Цвет — семейство товара (единое для всех графиков: считается по всему датасету, а не по выбранной паре),
    над столбиком — значение. `month` в формате "2026-09".
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    d = df.copy()
    d["month"] = d["created_at"].dt.strftime("%Y-%m")
    _, _, fam, _, fam_color = _sku_colors(d, metric, max_families)  # цвета по всему датасету
    names = analytics.latest_names(d, "sku")
    sub = d[(d[analytics.GEOS[geo]] == cluster) & (d["month"] == month)]
    if sub.empty:
        raise ValueError(f"Нет данных: {cluster!r}, {month}")
    s = sub.groupby("sku")[metric].sum().sort_values(ascending=False)
    unit = {"quantity": "шт.", "revenue": "руб."}.get(metric, "")
    fig, ax = plt.subplots(figsize=(max(9, 0.32 * len(s) + 2.5), 8))
    ax.bar(range(len(s)), s.values, color=[fam_color[fam[k]] for k in s.index], width=0.8)
    for i, v in enumerate(s.values):
        ax.text(i, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(range(len(s)), [f"{k}  {short_name(names[k], 28)}" for k in s.index], rotation=90, fontsize=7)
    ax.set_xlim(-0.7, len(s) - 0.3)
    ax.set_ylabel(unit)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    last = d["created_at"].max()
    partial = f", данные до {last:%d.%m}" if last.strftime("%Y-%m") == month and not last.is_month_end else ""
    ax.set_title(f"{cluster} — {month}{partial}\n{len(s)} SKU, всего {s.sum():,.0f} {unit}; топ-5 SKU дают "
                 f"{s.head(5).sum() / s.sum():.0%}", fontsize=11)
    used = [f for f in dict.fromkeys(fam[k] for k in s.index)]
    ax.legend(handles=[Patch(color=fam_color[f], label=f) for f in used], loc="upper right", fontsize=8,
              title="Семейство товара")
    fig.tight_layout()
    return fig


def save_png_pdf(fig, base: str, dpi: int = 150) -> tuple[str, str]:
    """Сохранить рисунок как `base.png` (растр, `dpi` ppi) и `base.pdf` (вектор, текст остаётся текстом)."""
    import matplotlib

    with matplotlib.rc_context({"pdf.fonttype": 42}):  # TrueType: текст в PDF выделяется и ищется
        fig.savefig(f"{base}.png", dpi=dpi)
        fig.savefig(f"{base}.pdf")
    return f"{base}.png", f"{base}.pdf"


def seasonality(df: pd.DataFrame, metric: str = "quantity"):
    """Сезонность: по оси X — месяц года, линия на каждый год. Видно провалы (паузы в продажах) и пики.

    Текущий (неполный) месяц последнего года не рисуется.
    """
    import matplotlib.pyplot as plt

    d = df.copy()
    d["year"], d["mon"] = d["created_at"].dt.year, d["created_at"].dt.month
    last = d["created_at"].max()
    if not last.is_month_end:
        d = d[~((d["year"] == last.year) & (d["mon"] == last.month))]
    pv = d.pivot_table(index="mon", columns="year", values=metric, aggfunc="sum").reindex(range(1, 13))
    fig, ax = plt.subplots(figsize=(11, 4.5))
    cmap = plt.get_cmap("viridis")
    for k, y in enumerate(pv.columns):
        ax.plot(pv.index, pv[y].values, marker="o", ms=4, lw=2 if y == pv.columns[-1] else 1.5,
                color=cmap(k / max(len(pv.columns) - 1, 1)), label=str(y))
    ax.set_xticks(range(1, 13), ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"])
    ax.set_ylabel({"quantity": "шт.", "revenue": "руб."}.get(metric, ""))
    ax.set_title("Сезонность: продажи по месяцам года (линия — год; пропуск линии — месяц без продаж)")
    ax.grid(alpha=0.3)
    ax.legend(title="Год", ncol=5, fontsize=8)
    fig.tight_layout()
    return fig
