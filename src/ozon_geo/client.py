"""Клиент Ozon Seller API (только чтение).

Документация: https://docs.ozon.ru/api/seller/
Ключ создаётся в ЛК: Настройки -> API-ключи (достаточно роли «Администратор» или «Только чтение»).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator

import requests

BASE_URL = "https://api-seller.ozon.ru"
PAGE_LIMIT = 1000
CHUNK_DAYS = 30  # Ozon ограничивает ширину окна фильтра по датам


class OzonError(RuntimeError):
    pass


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def date_chunks(since: datetime, to: datetime, days: int = CHUNK_DAYS) -> Iterator[tuple[datetime, datetime]]:
    cur = since
    while cur < to:
        nxt = min(cur + timedelta(days=days), to)
        yield cur, nxt
        cur = nxt


class OzonClient:
    def __init__(self, client_id: str | None = None, api_key: str | None = None,
                 base_url: str = BASE_URL, session: requests.Session | None = None,
                 max_retries: int = 5, backoff: float = 1.0):
        self.client_id = client_id or os.environ.get("OZON_CLIENT_ID", "")
        self.api_key = api_key or os.environ.get("OZON_API_KEY", "")
        if not self.client_id or not self.api_key:
            raise OzonError("Задайте OZON_CLIENT_ID и OZON_API_KEY (переменные окружения или аргументы)")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff = backoff

    def _post(self, path: str, body: dict) -> dict:
        headers = {"Client-Id": str(self.client_id), "Api-Key": self.api_key,
                   "Content-Type": "application/json"}
        for attempt in range(self.max_retries):
            try:
                resp = self.session.post(self.base_url + path, json=body, headers=headers, timeout=60)
            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    raise OzonError(f"{path}: {e}") from e
                time.sleep(self.backoff * 2 ** attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries - 1:
                    raise OzonError(f"{path}: HTTP {resp.status_code} {resp.text[:200]}")
                time.sleep(self.backoff * 2 ** attempt)
                continue
            if resp.status_code != 200:
                raise OzonError(f"{path}: HTTP {resp.status_code} {resp.text[:300]}")
            return resp.json()
        raise OzonError(f"{path}: исчерпаны попытки")

    # --- отправления ---------------------------------------------------------------------
    def iter_fbs_postings(self, since: datetime, to: datetime) -> Iterator[dict]:
        """FBS/rFBS отправления. Город — в analytics_data."""
        for lo, hi in date_chunks(since, to):
            offset = 0
            while True:
                body = {"dir": "ASC", "limit": PAGE_LIMIT, "offset": offset,
                        "filter": {"since": _iso(lo), "to": _iso(hi)},
                        "with": {"analytics_data": True, "financial_data": True}}
                result = self._post("/v3/posting/fbs/list", body).get("result", {})
                postings = result.get("postings", [])
                for p in postings:
                    yield p
                if not result.get("has_next") or not postings:
                    break
                offset += len(postings)

    def iter_fbo_postings(self, since: datetime, to: datetime) -> Iterator[dict]:
        """FBO отправления (со склада Ozon)."""
        for lo, hi in date_chunks(since, to):
            offset = 0
            while True:
                body = {"dir": "ASC", "limit": PAGE_LIMIT, "offset": offset, "translit": False,
                        "filter": {"since": _iso(lo), "to": _iso(hi)},
                        "with": {"analytics_data": True, "financial_data": True}}
                postings = self._post("/v2/posting/fbo/list", body).get("result") or []
                for p in postings:
                    yield p
                if len(postings) < PAGE_LIMIT:
                    break
                offset += len(postings)

    # --- товары и категории ----------------------------------------------------------------
    def product_categories(self, offer_ids: list[str]) -> dict[str, tuple[int, int]]:
        """offer_id -> (description_category_id, type_id)."""
        out: dict[str, tuple[int, int]] = {}
        ids = list(dict.fromkeys(offer_ids))
        for i in range(0, len(ids), 1000):
            data = self._post("/v3/product/info/list", {"offer_id": ids[i:i + 1000]})
            items = data.get("items") or data.get("result", {}).get("items", [])
            for it in items:
                cat, typ = it.get("description_category_id"), it.get("type_id")
                if it.get("offer_id") and cat is not None:
                    out[str(it["offer_id"])] = (int(cat), int(typ or 0))
        return out

    def category_names(self) -> dict[tuple[str, int], str]:
        """{('category', id): имя, ('type', id): имя} из дерева категорий."""
        data = self._post("/v1/description-category/tree", {"language": "DEFAULT"})
        names: dict[tuple[str, int], str] = {}

        def walk(nodes: list[dict]) -> None:
            for n in nodes:
                if "description_category_id" in n:
                    names[("category", int(n["description_category_id"]))] = n.get("category_name", "")
                if "type_id" in n:
                    names[("type", int(n["type_id"]))] = n.get("type_name", "")
                walk(n.get("children") or [])

        walk(data.get("result", []))
        return names
