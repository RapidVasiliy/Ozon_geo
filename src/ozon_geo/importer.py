"""Импорт CSV, выгруженного из личного кабинета Ozon (отчёт по отправлениям).

Разделитель «;», кавычки «"». Персональные данные покупателя (имя, email, телефон, адрес и т.п.)
не читаются и в базу не попадают. Категорий в этом отчёте нет — их можно задать отдельно
(`read_category_map`) или получить через API.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .store import Store

# поле хранилища -> колонка отчёта
COLUMNS = {
    "posting_number": "Номер отправления",
    "created": "Принят в обработку",
    "status": "Статус",
    "cancelled_at": "Дата отмены",
    "sku": "SKU",
    "offer_id": "Артикул",
    "name": "Название товара",
    "quantity": "Количество",
    "paid": "Оплачено покупателем",
    "cluster_to": "Кластер доставки",
    "cluster_from": "Кластер отгрузки",
    "region": "Регион доставки",
    "city": "Город доставки",
    "delivery_type": "Способ доставки",
    "warehouse": "Склад отгрузки",
}
REQUIRED = ("posting_number", "created", "sku", "quantity", "cluster_to", "city")


def _read(path: str | Path, sep: str | None = ";", **kw) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return pd.read_csv(path, sep=sep, engine="python", dtype=str, encoding=enc,
                               keep_default_na=False, **kw)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: не удалось определить кодировку (ожидались UTF-8 или Windows-1251)")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(",", ".", regex=False).str.replace(r"\s", "", regex=True),
                         errors="coerce").fillna(0.0)


def read_postings_csv(path: str | Path) -> pd.DataFrame:
    head = _read(path, nrows=0)
    missing = [COLUMNS[k] for k in REQUIRED if COLUMNS[k] not in head.columns]
    if missing:
        raise ValueError(f"В файле нет обязательных колонок: {', '.join(missing)}. "
                         f"Найдены: {', '.join(head.columns[:12])}...")
    use = [c for c in COLUMNS.values() if c in head.columns]  # только нужные — ПДн не читаются
    raw = _read(path, usecols=use)
    df = pd.DataFrame({k: raw[v] if v in raw.columns else "" for k, v in COLUMNS.items()})
    df["quantity"] = _num(df["quantity"]).clip(lower=1).astype(int)
    df["paid"] = _num(df["paid"])
    # время в отчёте кабинета — UTC: сверено с in_process_at из API (совпадает секунда в секунду)
    df["created"] = pd.to_datetime(df["created"], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%SZ").fillna("")
    cancelled = df["cancelled_at"].str.strip().ne("") | df["status"].str.lower().str.startswith("отмен")
    df.loc[cancelled, "status"] = "cancelled"
    return df


def import_postings_files(store: Store, paths: list[str | Path], log=print) -> int:
    """Импорт нескольких выгрузок. Пересекающиеся отправления берутся из самой свежей выгрузки
    (по дате последнего заказа в файле), поэтому порядок файлов в аргументах не важен."""
    frames = [(p, read_postings_csv(p)) for p in paths]
    frames.sort(key=lambda t: t[1]["created"].replace("", pd.NA).dropna().max() if t[1]["created"].ne("").any() else "")
    total = 0
    for p, df in frames:
        if df.empty:
            log(f"{Path(p).name}: файл пустой (только заголовок), пропущен")
            continue
        total += _import_frame(store, df, log)
    return total


def import_postings_csv(store: Store, path: str | Path, log=print) -> int:
    return _import_frame(store, read_postings_csv(path), log)


def _import_frame(store: Store, df: pd.DataFrame, log=print) -> int:
    store.conn.execute("PRAGMA synchronous=OFF")
    n = 0
    for number, g in df.groupby("posting_number", sort=False):
        first = g.iloc[0]
        store.upsert_posting({
            "posting_number": number, "status": first["status"], "in_process_at": first["created"],
            "analytics_data": {"city": first["city"], "region": first["region"],
                               "delivery_type": first["delivery_type"], "warehouse_name": first["warehouse"]},
            "financial_data": {"cluster_from": first["cluster_from"], "cluster_to": first["cluster_to"]},
            "products": [{"sku": r.sku, "offer_id": r.offer_id, "name": r.name, "quantity": r.quantity,
                          "price": r.paid} for r in g.itertuples()],
        }, "csv")
        n += 1
    log(f"Импортировано отправлений: {n}, позиций: {len(df)}")
    return n


def read_category_map(path: str | Path) -> dict[str, str]:
    """CSV с колонками «Артикул» (или offer_id) и «Категория» (или category)."""
    df = _read(path, sep=None)  # разделитель определяется автоматически
    cols = {c.strip().lower(): c for c in df.columns}
    o = cols.get("артикул") or cols.get("offer_id")
    c = cols.get("категория") or cols.get("category")
    if not o or not c:
        raise ValueError("Нужны колонки «Артикул» и «Категория» (или offer_id и category)")
    df = df[(df[o].str.strip() != "") & (df[c].str.strip() != "")]
    return dict(zip(df[o].str.strip(), df[c].str.strip()))
