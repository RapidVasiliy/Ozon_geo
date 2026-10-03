"""Синтетические данные в формате ответа Ozon — чтобы пробовать приложение без API-ключей."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from .store import Store

CITIES = {"Москва": 1.0, "Санкт-Петербург": 0.5, "Новосибирск": 0.2, "Екатеринбург": 0.22,
          "Казань": 0.15, "Краснодар": 0.18, "Красноярск": 0.1, "Хабаровск": 0.06}
# категория -> (id, вес, склонность к городам, зимний сезонный множитель)
CATEGORIES = {
    "Одежда": (1, 1.0, {"Москва": 1.2}, 0.3),
    "Товары для дома": (2, 0.8, {}, 0.0),
    "Спорт и отдых": (3, 0.5, {"Красноярск": 2.0, "Новосибирск": 1.6, "Краснодар": 0.6}, 0.5),
    "Электроника": (4, 0.7, {"Санкт-Петербург": 1.3}, 0.1),
}


def generate(store: Store, days: int = 365, seed: int = 0, base_orders_per_day: int = 40) -> int:
    rng = np.random.default_rng(seed)
    end = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    cities, cw = list(CITIES), np.array(list(CITIES.values()))
    n = 0
    names = {("category", cid): c for c, (cid, *_rest) in CATEGORIES.items()}
    offers = {c: [f"{cid:02d}-{k}" for k in range(1, 6)] for c, (cid, *_r) in CATEGORIES.items()}
    mapping = {o: (CATEGORIES[c][0], CATEGORIES[c][0] * 10) for c, os_ in offers.items() for o in os_}
    for d in range(days):
        day = end - timedelta(days=days - d)
        winter = np.cos(2 * np.pi * (day.timetuple().tm_yday - 15) / 365)  # 1 в январе, -1 в июле
        for cat, (cid, w, aff, amp) in CATEGORIES.items():
            p = cw * np.array([aff.get(c, 1.0) for c in cities])
            p = p / p.sum()
            lam = base_orders_per_day * w * (1 + amp * winter) / len(CATEGORIES)
            for city in rng.choice(cities, size=rng.poisson(max(lam, 0.1)), p=p):
                offer = str(rng.choice(offers[cat]))
                n += 1
                store.upsert_posting({
                    "posting_number": f"DEMO-{n:07d}", "status": "cancelled" if rng.random() < 0.05 else "delivered",
                    "in_process_at": (day + timedelta(minutes=int(rng.integers(0, 600)))).isoformat(),
                    "analytics_data": {"city": city, "region": city, "delivery_type": "PVZ"},
                    "products": [{"sku": hash(offer) % 10**9, "offer_id": offer, "name": f"{cat} {offer}",
                                  "quantity": int(rng.integers(1, 3)),
                                  "price": str(round(float(rng.uniform(300, 5000)), 2))}]}, "fbs")
    store.save_products(mapping)
    store.save_category_names(names)
    return n
