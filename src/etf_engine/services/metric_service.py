from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
MINIMUM_OBSERVATIONS = 20


def _series(frame: pd.DataFrame | None) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    column = "adj_close" if "adj_close" in frame else "close"
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def calculate_metrics(
    etf_id: str,
    prices: pd.DataFrame,
    benchmark: pd.DataFrame | None,
    risk_free_rate: float = 0.015,
) -> list[dict]:
    price = _series(prices)
    benchmark_price = _series(benchmark)
    if len(price) < MINIMUM_OBSERVATIONS:
        return []

    one_year_eligible = len(price) >= TRADING_DAYS
    window = price.iloc[-TRADING_DAYS:] if one_year_eligible else price
    returns = window.pct_change().dropna()
    years = len(window) / TRADING_DAYS
    available_return = float(window.iloc[-1] / window.iloc[0] - 1)
    annual_return = (
        float((window.iloc[-1] / window.iloc[0]) ** (1 / years) - 1) if one_year_eligible else None
    )
    volatility = float(returns.std() * np.sqrt(TRADING_DAYS))
    sharpe = (
        (annual_return - risk_free_rate) / volatility
        if annual_return is not None and volatility
        else None
    )
    drawdown = window / window.cummax() - 1

    alpha = beta = tracking_error = None
    benchmark_returns = benchmark_price.pct_change().dropna()
    common = returns.index.intersection(benchmark_returns.index)
    if len(common) >= MINIMUM_OBSERVATIONS:
        etf_returns = returns.loc[common]
        aligned_benchmark = benchmark_returns.loc[common]
        variance = float(aligned_benchmark.var())
        beta = float(etf_returns.cov(aligned_benchmark) / variance) if variance else None
        if beta is not None:
            alpha = float((etf_returns.mean() - beta * aligned_benchmark.mean()) * TRADING_DAYS)
        tracking_error = float((etf_returns - aligned_benchmark).std() * np.sqrt(TRADING_DAYS))

    metrics = {
        "annualized_volatility": (volatility * 100, "percent", "available"),
        "sharpe_ratio": (sharpe, "ratio", "1y"),
        "max_drawdown": (float(drawdown.min()) * 100, "percent", "available"),
        "alpha": (alpha * 100 if alpha is not None else None, "percent", "1y"),
        "beta": (beta, "ratio", "1y"),
        "tracking_error": (
            tracking_error * 100 if tracking_error is not None else None,
            "percent",
            "1y",
        ),
        "data_years": (len(price) / TRADING_DAYS, "years", "available"),
    }
    if one_year_eligible:
        metrics["total_return_1y"] = (available_return * 100, "percent", "1y")
        metrics["annualized_return"] = (annual_return * 100, "percent", "1y")
    else:
        metrics["total_return_since_inception"] = (
            available_return * 100,
            "percent",
            "available",
        )

    as_of = price.index[-1].date().isoformat()
    return [
        {
            "etf_id": etf_id,
            "metric_code": code,
            "value": round(value, 4) if value is not None else None,
            "unit": unit,
            "as_of": as_of,
            "period": period,
            "source": "calculated",
        }
        for code, (value, unit, period) in metrics.items()
    ]
