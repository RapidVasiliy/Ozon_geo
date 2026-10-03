"""SQLite-хранилище: отправления, позиции, категории товаров."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings(
  posting_number TEXT PRIMARY KEY, scheme TEXT, status TEXT, created_at TEXT,
  city TEXT, region TEXT, delivery_type TEXT, warehouse TEXT);
CREATE TABLE IF NOT EXISTS items(
  posting_number TEXT, offer_id TEXT, sku TEXT, name TEXT, quantity INTEGER, price REAL,
  PRIMARY KEY(posting_number, offer_id, sku));
CREATE TABLE IF NOT EXISTS products(
  offer_id TEXT PRIMARY KEY, category_id INTEGER, type_id INTEGER);
CREATE TABLE IF NOT EXISTS category_names(
  kind TEXT, id INTEGER, name TEXT, PRIMARY KEY(kind, id));
CREATE INDEX IF NOT EXISTS ix_postings_created ON postings(created_at);
"""

UNKNOWN_CITY = "(не определён)"
UNKNOWN_CATEGORY = "(без категории)"


class Store:
    def __init__(self, path: str | Path = "ozon.db"):
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def upsert_posting(self, p: dict, scheme: str) -> None:
        """p — сырое отправление Ozon (FBS или FBO). Идемпотентно по posting_number."""
        a = p.get("analytics_data") or {}
        created = p.get("in_process_at") or p.get("created_at") or ""
        number = p["posting_number"]
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO postings VALUES (?,?,?,?,?,?,?,?)",
                (number, scheme, p.get("status", ""), created,
                 (a.get("city") or "").strip(), (a.get("region") or "").strip(),
                 a.get("delivery_type", ""), a.get("warehouse_name") or a.get("warehouse", "")))
            self.conn.execute("DELETE FROM items WHERE posting_number=?", (number,))
            for it in p.get("products", []):
                self.conn.execute(
                    "INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?)",
                    (number, str(it.get("offer_id", "")), str(it.get("sku", "")), it.get("name", ""),
                     int(it.get("quantity", 1)), float(it.get("price") or 0)))

    def missing_offer_ids(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT offer_id FROM items WHERE offer_id<>'' "
            "AND offer_id NOT IN (SELECT offer_id FROM products)").fetchall()
        return [r[0] for r in rows]

    def save_products(self, mapping: dict[str, tuple[int, int]]) -> None:
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO products VALUES (?,?,?)",
                                  [(o, c, t) for o, (c, t) in mapping.items()])

    def save_category_names(self, names: dict[tuple[str, int], str]) -> None:
        with self.conn:
            self.conn.executemany("INSERT OR REPLACE INTO category_names VALUES (?,?,?)",
                                  [(k, i, n) for (k, i), n in names.items()])

    def sales_frame(self) -> pd.DataFrame:
        """Плоская таблица «позиция заказа» с городом, категорией и типом товара."""
        q = f"""
        SELECT p.posting_number, p.scheme, p.status, p.created_at,
               COALESCE(NULLIF(p.city,''), '{UNKNOWN_CITY}') AS city,
               COALESCE(NULLIF(p.region,''), '') AS region,
               i.offer_id, i.name, i.quantity, i.price,
               COALESCE(cn.name, CASE WHEN pr.category_id IS NULL THEN '{UNKNOWN_CATEGORY}'
                                      ELSE 'category ' || pr.category_id END) AS category,
               COALESCE(tn.name, CASE WHEN pr.type_id IS NULL THEN '{UNKNOWN_CATEGORY}'
                                      ELSE 'type ' || pr.type_id END) AS product_type
        FROM postings p JOIN items i USING(posting_number)
        LEFT JOIN products pr ON pr.offer_id = i.offer_id
        LEFT JOIN category_names cn ON cn.kind='category' AND cn.id = pr.category_id
        LEFT JOIN category_names tn ON tn.kind='type' AND tn.id = pr.type_id
        """
        df = pd.read_sql_query(q, self.conn)
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        df["revenue"] = df["price"] * df["quantity"]
        return df
