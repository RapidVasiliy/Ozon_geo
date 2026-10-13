import pytest
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
               "financial_data": {"cluster_from": "Москва", "cluster_to": "Поволжье"},
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
        sync(FakeClient(), st, schemes=("fbs", "fbo"), log=lambda s: None)
    df = analytics.prepare(st.sales_frame())
    assert len(df) == 2  # отменённое исключено
    g = analytics.category_city(df).set_index(["category", "destination"])
    assert g.loc[("Игрушки", "Казань"), "quantity"] == 2
    assert g.loc[("Игрушки", "Казань"), "revenue"] == 200
    assert ("(без категории)", "(не определён)") in g.index
    assert len(analytics.prepare(st.sales_frame(), include_cancelled=True)) == 3


def test_demo_affinity_and_forecast():
    st = Store(":memory:")
    generate(st, days=400, seed=1)
    df = analytics.prepare(st.sales_frame())
    g = analytics.category_city(df).set_index(["category", "destination"])
    assert g.loc[("Спорт и отдых", "Красноярск"), "lift"] > 1.3  # заложенная склонность найдена
    panel = analytics.weekly_panel(df)
    assert (panel.groupby(["category", "destination"]).size().nunique()) == 1  # без пропусков недель
    for m in (forecast.MovingAverage(4), forecast.SeasonalNaive(52)):
        r = forecast.backtest(panel, m, 4)
        assert 0 <= r["wape"] < 2


def test_cluster_aggregation_and_db_migration(tmp_path):
    st = Store(":memory:")
    sync(FakeClient(), st, schemes=("fbs", "fbo"), log=lambda s: None)
    df = analytics.prepare(st.sales_frame())
    g = analytics.category_city(df, geo="cluster").set_index(["category", "destination"])
    assert g.loc[("Игрушки", "Поволжье"), "quantity"] == 2
    assert ("(без категории)", "(не определён)") in g.index  # FBO без financial_data

    # БД, созданная до появления кластеров, мигрирует без потери данных
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE postings(posting_number TEXT PRIMARY KEY, scheme TEXT, status TEXT, created_at TEXT,"
              " city TEXT, region TEXT, delivery_type TEXT, warehouse TEXT)")
    c.execute("INSERT INTO postings VALUES ('old','fbs','delivered','2026-01-01','Омск','','','')")
    c.commit(); c.close()
    st2 = Store(path)
    assert st2.conn.execute("SELECT city, cluster_to FROM postings").fetchall() == [("Омск", None)]


def test_demo_clusters():
    st = Store(":memory:")
    generate(st, days=60, seed=2)
    df = analytics.prepare(st.sales_frame())
    assert set(df["cluster"]) >= {"Сибирь", "Урал"}


def test_fbs_v4_cursor_pagination(monkeypatch):
    from datetime import datetime, timezone

    calls = []

    def fake_post(self, path, body):
        calls.append((path, dict(body)))
        pages = {"": ({"has_next": True, "cursor": "c1", "postings": [{"posting_number": "1"}]}),
                 "c1": ({"has_next": False, "cursor": "", "postings": [{"posting_number": "2"}]})}
        return pages[body["cursor"]]

    monkeypatch.setattr(OzonClient, "_post", fake_post)
    c = OzonClient("1", "k")
    a, b = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 3, 1, tzinfo=timezone.utc)
    got = [p["posting_number"] for p in c.iter_fbs_postings(a, b)]
    assert got == ["1", "2"]  # одно окно (< 90 дней), две страницы по курсору
    assert [x[0] for x in calls] == ["/v4/posting/fbs/list"] * 2
    assert calls[1][1]["cursor"] == "c1" and "offset" not in calls[1][1]
    assert calls[0][1]["with"] == {"analytics_data": True, "financial_data": True}
    assert calls[0][1]["sort_dir"] == "ASC" and "dir" not in calls[0][1] and calls[0][1]["limit"] == 100
    assert set(calls[0][1]["filter"]) == {"since", "to"}  # без фильтров по статусам/складам: иначе вернётся пусто


def test_real_v4_posting_shape():
    """Структура отправления из реального ответа /v4/posting/fbs/list (цена — объект, кластеры в financial_data)."""
    posting = {
        "posting_number": "39430909-0154-12", "status": "delivered", "delivery_schema": "fbs",
        "in_process_at": "2026-09-01T02:20:48Z", "customer": None, "addressee": None,
        "delivery_method": {"warehouse": "Ветеранов"},
        "products": [{"offer_id": "П1223", "name": "Парафинированная бумага", "sku": 1755765499, "quantity": 2,
                      "price": {"amount": "279", "currency": "RUB"}}],
        "analytics_data": {"region": "", "city": "", "delivery_type": "PVZ", "warehouse": "Ветеранов"},
        "financial_data": {"products": [{"product_id": 1755765499, "price": 279,
                                         "customer_price": {"amount": "241.9", "currency": "RUB"}}],
                           "cluster_from": "Санкт-Петербург и СЗО", "cluster_to": "Москва, МО и Дальние регионы"},
    }
    st = Store(":memory:")
    st.upsert_posting(posting, "fbs")
    df = st.sales_frame().iloc[0]
    assert df["cluster"] == "Москва, МО и Дальние регионы" and df["city"] == "(не определён)"
    assert df["price"] == 241.9 and df["revenue"] == pytest.approx(483.8)  # цена покупателя × количество
    assert df["created_at"].strftime("%Y-%m-%d %H:%M") == "2026-09-01 05:20"  # UTC -> Москва
    # без financial_data.products — берётся price.amount
    posting["financial_data"] = {"cluster_to": "Уфа"}
    st.upsert_posting(posting, "fbs")
    assert st.sales_frame().iloc[0]["price"] == 279.0


def test_old_v4_posting_without_customer_price():
    """Старое отправление (2023): customer_price = 0 с пустой валютой -> берём price.amount, а не 0."""
    posting = {
        "posting_number": "0108964297-0104-3", "status": "delivered", "in_process_at": "2023-10-13T07:25:33Z",
        "products": [{"offer_id": "П0998", "name": "Восковые салфетки", "sku": 810066919, "quantity": 1,
                      "price": {"amount": "281", "currency": "RUB"}}],
        "analytics_data": {"region": "", "city": "", "warehouse": "Ветеранов"},
        "financial_data": {"products": [{"product_id": 810066919, "price": 281,
                                         "customer_price": {"amount": "0", "currency": ""}}],
                           "cluster_from": "Санкт-Петербург и СЗО", "cluster_to": "Москва, МО и Дальние регионы"},
    }
    st = Store(":memory:")
    st.upsert_posting(posting, "fbs")
    row = st.sales_frame().iloc[0]
    assert row["price"] == 281.0 and row["cluster"] == "Москва, МО и Дальние регионы"
    assert row["created_at"].strftime("%Y-%m-%d") == "2023-10-13"
