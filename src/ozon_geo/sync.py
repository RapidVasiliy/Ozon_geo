"""Загрузка данных из Ozon в локальное хранилище."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from .client import OzonClient
from .store import Store


def sync(client: OzonClient, store: Store, since: datetime | None = None, to: datetime | None = None,
         schemes: tuple[str, ...] = ("fbs",), log: Callable[[str], None] = print) -> dict[str, int]:
    to = to or datetime.now(timezone.utc)
    since = since or to - timedelta(days=90)
    client.progress = log
    counts: dict[str, int] = {}
    sources = {"fbs": client.iter_fbs_postings, "fbo": client.iter_fbo_postings}
    for scheme in schemes:
        n = 0
        for posting in sources[scheme](since, to):
            store.upsert_posting(posting, scheme)
            n += 1
            if n % 500 == 0:  # прогресс: загрузка многолетней истории идёт долго
                log(f"{scheme.upper()}: {n} отправлений, дата последнего — {str(posting.get('in_process_at') or posting.get('created_at') or '')[:10]}")
        counts[scheme] = n
        log(f"{scheme.upper()}: загружено отправлений — {n}")

    missing = store.missing_offer_ids()
    if missing:
        store.save_products(client.product_categories(missing))
        log(f"Категории для {len(missing)} артикулов обновлены")
        store.save_category_names(client.category_names())
    return counts
