import pytest
import matplotlib

matplotlib.use("Agg")

from ozon_geo import analytics, viz
from ozon_geo.demo import generate
from ozon_geo.store import Store


def _df():
    st = Store(":memory:")
    generate(st, days=200, seed=3)
    return analytics.prepare(st.sales_frame())


def test_sku_family_and_short_name():
    assert viz.sku_family('Бумага для выпечки 38см*5м "Полоски"') == "Бумага для выпечки"
    assert viz.sku_family("12345") == "Прочее"
    assert viz.short_name('Бумага 38см "Полоски бордовые" ВЫРУЧАЛОЧКА') == "Полоски бордовые"
    assert viz.short_name("Без кавычек", 5) == "Без к"


def test_monthly_figures_render():
    df = _df()
    for metric in ("quantity", "revenue"):
        f1 = viz.monthly_sku_by_cluster(df, metric, top_clusters=3)
        f2 = viz.monthly_sku_heatmap(df, metric)
        assert len(f1.axes) >= 4  # 3 кластера + «Остальные» (+ пустые панели)
        assert f2.axes[0].get_xticklabels()[0].get_text().startswith("20")


def test_cluster_month_bars_sorted_and_saved(tmp_path):
    df = _df()
    df["month"] = df["created_at"].dt.strftime("%Y-%m")
    g = df.groupby(["cluster", "month"])["quantity"].sum().idxmax()
    fig = viz.cluster_month_bars(df, *g)
    heights = [p.get_height() for p in fig.axes[0].patches]
    assert heights == sorted(heights, reverse=True)  # от популярных SKU к редким
    png, pdf = viz.save_png_pdf(fig, str(tmp_path / "chart"), dpi=100)
    assert open(pdf, "rb").read(4) == b"%PDF"
    from PIL import Image
    assert Image.open(png).info["dpi"][0] == pytest.approx(100, abs=1)
    with pytest.raises(ValueError):
        viz.cluster_month_bars(df, "нет такого кластера", g[1])
