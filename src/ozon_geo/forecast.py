"""Задел под предиктивную аналитику: базовые прогнозы спроса по паре категория × город.

Любая будущая модель (CatBoost, Prophet, ...) должна реализовать тот же интерфейс
`fit(panel)` / `predict(horizon) -> DataFrame[category, city, week, forecast]`
и сравнивается с этими бейзлайнами через `backtest`.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np
import pandas as pd

KEYS = ["category", "city"]


class Forecaster(Protocol):
    def fit(self, panel: pd.DataFrame) -> "Forecaster": ...
    def predict(self, horizon: int) -> pd.DataFrame: ...


class MovingAverage:
    """Прогноз = среднее за последние `window` недель (плоский)."""

    def __init__(self, window: int = 4):
        self.window = window

    def fit(self, panel: pd.DataFrame) -> "MovingAverage":
        self.last_week_ = panel["week"].max()
        recent = panel[panel["week"] > self.last_week_ - pd.Timedelta(weeks=self.window)]
        self.level_ = recent.groupby(KEYS)["quantity"].mean().rename("forecast").reset_index()
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        weeks = [self.last_week_ + pd.Timedelta(weeks=k) for k in range(1, horizon + 1)]
        out = self.level_.merge(pd.DataFrame({"week": weeks}), how="cross")
        return out[KEYS + ["week", "forecast"]]


class SeasonalNaive:
    """Прогноз = значение той же недели `season` недель назад (по умолчанию год); при нехватке
    истории — откат на скользящее среднее."""

    def __init__(self, season: int = 52, fallback_window: int = 4):
        self.season, self.fallback = season, MovingAverage(fallback_window)

    def fit(self, panel: pd.DataFrame) -> "SeasonalNaive":
        self.panel_ = panel
        self.fallback.fit(panel)
        return self

    def predict(self, horizon: int) -> pd.DataFrame:
        base = self.fallback.predict(horizon)
        lag = self.panel_[KEYS + ["week", "quantity"]].copy()
        lag["week"] = lag["week"] + pd.Timedelta(weeks=self.season)
        out = base.merge(lag, on=KEYS + ["week"], how="left")
        out["forecast"] = out["quantity"].fillna(out["forecast"])
        return out[KEYS + ["week", "forecast"]]


def backtest(panel: pd.DataFrame, model: Forecaster, horizon: int = 4) -> dict[str, float]:
    """Обучаемся на всём, кроме последних `horizon` недель; WAPE/MAE по оставленным."""
    cutoff = panel["week"].max() - pd.Timedelta(weeks=horizon)
    train, test = panel[panel["week"] <= cutoff], panel[panel["week"] > cutoff]
    pred = model.fit(train).predict(horizon)
    m = test.merge(pred, on=KEYS + ["week"], how="left").fillna({"forecast": 0.0})
    err = (m["quantity"] - m["forecast"]).abs()
    return {"mae": float(err.mean()), "wape": float(err.sum() / max(m["quantity"].sum(), 1e-9)),
            "n": int(len(m))}
