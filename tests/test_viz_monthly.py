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
    assert viz.sku_family("Сердечки розовые силиконизированная бумага с принтом") == "Бумага для выпечки"
    assert viz.sku_family("Подпергамент Пицца 5м") == "Подпергамент"  # раньше правила «пергамент»
    assert viz.sku_family("Парафинированная бумага в листах для компрессов") == "Парафинированная / вощёная"
    assert viz.sku_family("Компрессная бумага в рулоне") == "Компрессная бумага"
    assert viz.sku_family("Восковые салфетки одноразовые") == "Восковые салфетки"
    assert viz.sku_family("Школа") == "Прочее" and viz.sku_family("12345") == "Прочее"
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


def test_long_history_and_seasonality_render():
    st = Store(":memory:")
    generate(st, days=900, seed=4)  # > 24 месяцев: тепловая карта без подписей в клетках, прореженные оси
    df = analytics.prepare(st.sales_frame())
    f = viz.monthly_sku_heatmap(df)
    assert not f.axes[0].texts  # числа в клетках не рисуются при длинной истории
    assert f.get_size_inches()[0] <= 26
    viz.monthly_sku_by_cluster(df, top_clusters=3)
    fig = viz.seasonality(df)
    assert len(fig.axes[0].lines) >= 2 and fig.axes[0].get_xlim()[0] <= 1


def test_latest_name_is_used_for_renamed_sku():
    st = Store(":memory:")
    for i, (ts, name) in enumerate([("2026-01-01T10:00:00Z", "Старое название"), ("2026-03-01T10:00:00Z", "Подпергамент новое")]):
        st.upsert_posting({"posting_number": f"p{i}", "status": "delivered", "in_process_at": ts,
                           "financial_data": {"cluster_to": "К"},
                           "products": [{"sku": 7, "offer_id": "o", "name": name, "quantity": 1, "price": 1}]}, "fbs")
    df = analytics.prepare(st.sales_frame())
    assert analytics.latest_names(df, "sku")["7"] == "Подпергамент новое"
    assert viz.sku_family(analytics.latest_names(df, "sku")["7"]) == "Подпергамент"
