from datetime import datetime, timezone

import pandas as pd

from ozon_geo import analytics, forecast
from ozon_geo.client import OzonClient, date_chunks
from ozon_geo.demo import generate
from ozon_geo.store import Store
from ozon_geo.sync import sync


class FakeClient(OzonClient):
    def __init__(self):
        pass

    def iter_fbs_postings(self, since, to):
        yield {"posting_number": "A-1", "status": "delivered", "in_process_at": "2026-01-05T10:00:00Z",
               "analytics_data": {"city": "Казань", "region": "Татарстан"},
               "products": [{"sku": 1, "offer_id": "x", "name": "n", "quantity": 2, "price": "100.0"}]}
        yield {"posting_number": "A-2", "status": "cancelled", "in_process_at": "2026-01-06T10:00:00Z",
               "analytics_data": {"city": "Казань"},
               "products": [{"sku": 1, "offer_id": "x", "name": "n", "quantity": 1, "price": "100.0"}]}

    def iter_fbo_postings(self, since, to):
        yield {"posting_number": "B-1", "status": "delivered", "created_at": "2026-01-07T10:00:00Z",
               "analytics_data": {"city": ""}, "products": [{"sku": 2, "offer_id": "y", "quantity": 1, "price": "50"}]}

    def product_categories(self, offer_ids):
        return {"x": (10, 100)}

    def category_names(self):
        return {("category", 10): "Игрушки", ("type", 100): "Конструкторы"}


def test_date_chunks_cover_range():
    a, b = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 4, 1, tzinfo=timezone.utc)
    ch = list(date_chunks(a, b, 30))
    assert ch[0][0] == a and ch[-1][1] == b and len(ch) == 3


def test_sync_and_aggregate_idempotent():
    st = Store(":memory:")
    for _ in range(2):  # повторная загрузка не должна дублировать данные
        sync(FakeClient(), st, log=lambda s: None)
    df = analytics.prepare(st.sales_frame())
    assert len(df) == 2  # отменённое исключено
    g = analytics.category_city(df).set_index(["category", "city"])
    assert g.loc[("Игрушки", "Казань"), "quantity"] == 2
    assert g.loc[("Игрушки", "Казань"), "revenue"] == 200
    assert ("(без категории)", "(не определён)") in g.index
    assert len(analytics.prepare(st.sales_frame(), include_cancelled=True)) == 3


def test_demo_affinity_and_forecast():
    st = Store(":memory:")
    generate(st, days=400, seed=1)
    df = analytics.prepare(st.sales_frame())
    g = analytics.category_city(df).set_index(["category", "city"])
    assert g.loc[("Спорт и отдых", "Красноярск"), "lift"] > 1.3  # заложенная склонность найдена
    panel = analytics.weekly_panel(df)
    assert (panel.groupby(["category", "city"]).size().nunique()) == 1  # без пропусков недель
    for m in (forecast.MovingAverage(4), forecast.SeasonalNaive(52)):
        r = forecast.backtest(panel, m, 4)
        assert 0 <= r["wape"] < 2
