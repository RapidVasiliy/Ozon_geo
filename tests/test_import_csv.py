from pathlib import Path

import pytest

from ozon_geo import analytics
from ozon_geo.importer import import_postings_csv, read_category_map, read_postings_csv
from ozon_geo.store import Store

FIX = Path(__file__).parent / "fixtures"


def _frame(name="ozon_lk_postings.csv"):
    st = Store(":memory:")
    assert import_postings_csv(st, FIX / name, log=lambda s: None) == 4
    return st, st.sales_frame()


@pytest.mark.parametrize("name", ["ozon_lk_postings.csv", "ozon_lk_postings_cp1251.csv"])
def test_import_utf8_and_cp1251(name):
    st, df = _frame(name)
    assert len(df) == 4
    assert set(df["cluster"]) == {"Санкт-Петербург и СЗО", "Урал", "Сибирь"}
    assert df.loc[df["posting_number"] == "11111111-0001-1", "name"].iloc[0] == 'Бумага "Полоски"'  # "" разэкранировано
    # время московское -> UTC
    assert df.loc[df["posting_number"] == "11111111-0001-1", "created_at"].iloc[0].hour == 16


def test_status_money_and_empty_city():
    st, df = _frame()
    assert (df.set_index("posting_number")["status"]["11111111-0003-1"]) == "cancelled"
    d = analytics.prepare(df)
    assert len(d) == 3  # отменённое исключено
    row = d[d["posting_number"] == "11111111-0002-1"].iloc[0]
    assert row["quantity"] == 2 and round(row["revenue"], 2) == 336.34  # «Оплачено покупателем» — цена за штуку
    assert row["city"] == "(не определён)"
    assert d[d["posting_number"] == "11111111-0004-1"]["revenue"].iloc[0] == 300.5  # запятая как разделитель


def test_sku_by_cluster():
    _, df = _frame()
    g = analytics.category_city(analytics.prepare(df), level="sku", geo="cluster").set_index(["category", "destination"])
    assert g.loc[("1001", "Санкт-Петербург и СЗО"), "quantity"] == 3
    assert g.loc[("1001", "Санкт-Петербург и СЗО"), "name"] == 'Бумага "Полоски"'
    assert ("1002", "Урал") not in g.index  # отмена
    assert g.loc[("1002", "Сибирь"), "quantity"] == 1


def test_personal_data_not_stored():
    st, _ = _frame()
    dump = "\n".join(str(r) for t in ("postings", "items") for r in st.conn.execute(f"SELECT * FROM {t}"))
    assert "Иван Тестов" not in dump
    assert "Имя покупателя" not in read_postings_csv(FIX / "ozon_lk_postings.csv").columns


def test_missing_columns_message(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text('"Номер отправления";"SKU"\n"1";"2"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Кластер доставки"):
        read_postings_csv(bad)


def test_categories_map(tmp_path):
    m = tmp_path / "cat.csv"
    m.write_text("Артикул;Категория\nA1;Бумага для выпечки\nB2;Формы\n", encoding="utf-8")
    st, _ = _frame()
    st.save_category_map(read_category_map(m))
    d = analytics.prepare(st.sales_frame())
    g = analytics.category_city(d, geo="cluster").set_index(["category", "destination"])
    assert g.loc[("Бумага для выпечки", "Санкт-Петербург и СЗО"), "quantity"] == 3


def test_overlapping_files_newest_wins(tmp_path):
    from ozon_geo.importer import import_postings_files
    src = (FIX / "ozon_lk_postings.csv").read_text(encoding="utf-8-sig").splitlines()
    old = tmp_path / "old.csv"   # более старая выгрузка: одно отправление ещё «Ожидает сборки»
    new = tmp_path / "new.csv"   # свежая: оно же уже «Доставлен» + более поздний заказ
    old.write_text("\n".join(src[:2]) + "\n", encoding="utf-8-sig")
    late = src[1].replace("11111111-0001-1", "11111111-0009-1").replace("2026-10-12 19:19:14", "2026-10-20 10:00:00")
    new.write_text("\n".join([src[0], src[1].replace("Ожидает сборки", "Доставлен"), late]) + "\n", encoding="utf-8-sig")
    empty = tmp_path / "empty.csv"
    empty.write_text(src[0] + "\n", encoding="utf-8-sig")
    st = Store(":memory:")
    import_postings_files(st, [new, old, empty], log=lambda s: None)  # «неправильный» порядок
    df = st.sales_frame().set_index("posting_number")
    assert df.loc["11111111-0001-1", "status"] == "Доставлен"
    assert len(df) == 2
