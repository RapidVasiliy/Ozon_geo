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
