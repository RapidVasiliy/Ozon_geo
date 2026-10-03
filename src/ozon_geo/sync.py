"""Загрузка данных из Ozon в локальное хранилище."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from .client import OzonClient
from .store import Store


def sync(client: OzonClient, store: Store, since: datetime | None = None, to: datetime | None = None,
         schemes: tuple[str, ...] = ("fbs", "fbo"), log: Callable[[str], None] = print) -> dict[str, int]:
    to = to or datetime.now(timezone.utc)
    since = since or to - timedelta(days=90)
    counts: dict[str, int] = {}
    sources = {"fbs": client.iter_fbs_postings, "fbo": client.iter_fbo_postings}
    for scheme in schemes:
        n = 0
        for posting in sources[scheme](since, to):
            store.upsert_posting(posting, scheme)
            n += 1
        counts[scheme] = n
        log(f"{scheme.upper()}: загружено отправлений — {n}")

    missing = store.missing_offer_ids()
    if missing:
        store.save_products(client.product_categories(missing))
        log(f"Категории для {len(missing)} артикулов обновлены")
        store.save_category_names(client.category_names())
    return counts
