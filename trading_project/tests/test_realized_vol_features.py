"""
Prüft die Realized-Volatility-Merkmale ohne Börsenverbindung.

Der wichtigste Test ist `test_features_do_not_look_ahead`: er berechnet jedes
Merkmal einmal auf dem vollständigen Kursverlauf und einmal auf einem
abgeschnittenen. Stimmen die Werte an den gemeinsamen Zeitpunkten nicht
überein, benutzt das Merkmal Daten aus der Zukunft.

Ausführen:
    .venv/bin/python -m pytest trading_project/tests -q
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategies"))

from RealizedVolStrategy import (  # noqa: E402
    EPS,
    RealizedVolStrategy,
    bipower_variation,
    log_returns,
    realized_semivariance,
    realized_variance,
)


CANDLES = 3000
STARTUP = RealizedVolStrategy.startup_candle_count


@pytest.fixture(scope="module")
def ohlcv() -> pd.DataFrame:
    """Zufälliger Kursverlauf mit wechselnder Schwankungsbreite und Sprüngen."""
    rng = np.random.default_rng(20261015)

    # Volatilität selbst schwankt, damit die Messgrößen etwas zu messen haben.
    vol = 0.001 * np.exp(0.4 * np.cumsum(rng.normal(0, 0.05, CANDLES)))
    returns = rng.normal(0, 1, CANDLES) * vol

    # Ein paar Sprünge, damit sich Bipower Variation von RV unterscheidet.
    for idx in rng.choice(CANDLES, 12, replace=False):
        returns[idx] += rng.choice([-1, 1]) * 0.05

    close = 50_000 * np.exp(np.cumsum(returns))
    spread = np.abs(rng.normal(0, 1, CANDLES)) * vol * close

    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=CANDLES, freq="5min", tz="UTC"),
            "open": np.concatenate([[close[0]], close[:-1]]),
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.lognormal(3, 0.5, CANDLES),
        }
    )


@pytest.fixture(scope="module")
def strategy() -> RealizedVolStrategy:
    strat = RealizedVolStrategy.__new__(RealizedVolStrategy)
    strat.freqai_info = {"feature_parameters": {"label_period_candles": 24}}
    return strat


def build_features(strategy: RealizedVolStrategy, df: pd.DataFrame) -> pd.DataFrame:
    """Alle Merkmalsfunktionen nacheinander, wie FreqAI sie aufruft."""
    out = df.copy()
    for period in (12, 48, 288):
        expanded = strategy.feature_engineering_expand_all(out.copy(), period, {})
        for col in expanded.columns:
            if col.startswith("%-") and col.endswith("-period"):
                out[col.replace("-period", f"-{period}")] = expanded[col]
    out = strategy.feature_engineering_expand_basic(out, {})
    out = strategy.feature_engineering_standard(out, {})
    return out


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith("%-")]


# --------------------------------------------------------------------------
# Die Messgrößen selbst
# --------------------------------------------------------------------------


def test_realized_variance_matches_manual_sum(ohlcv):
    r = log_returns(ohlcv["close"])
    rv = realized_variance(r, 48)
    manual = sum(r.iloc[500 - k] ** 2 for k in range(48))
    assert rv.iloc[500] == pytest.approx(manual, rel=1e-12)


def test_semivariances_add_up_to_variance(ohlcv):
    r = log_returns(ohlcv["close"])
    up, down = realized_semivariance(r, 48)
    rv = realized_variance(r, 48)
    assert (up + down).dropna().values == pytest.approx(rv.dropna().values, rel=1e-10)


def test_semivariances_are_non_negative(ohlcv):
    r = log_returns(ohlcv["close"])
    up, down = realized_semivariance(r, 48)
    assert up.dropna().min() >= 0
    assert down.dropna().min() >= 0


def test_bipower_variation_is_below_rv_on_jumps(ohlcv):
    """
    Bei Sprüngen liegt BV unter RV — genau diese Differenz ist die
    Sprungkomponente. Über den ganzen Verlauf gemittelt muss sie positiv sein.
    """
    r = log_returns(ohlcv["close"])
    rv = realized_variance(r, 48)
    bv = bipower_variation(r, 48)
    jump = (rv - bv).clip(lower=0).dropna()
    assert jump.mean() > 0
    assert jump.max() > 0


def test_shares_stay_within_bounds(ohlcv, strategy):
    """Anteile sind Verhältnisse zur Gesamtschwankung und liegen in [0, 1]."""
    df = build_features(strategy, ohlcv)
    for col in ("%-downside_share-48", "%-jump_share-48"):
        values = df[col].iloc[STARTUP:]
        assert values.min() >= -1e-9, col
        assert values.max() <= 1 + 1e-9, col


# --------------------------------------------------------------------------
# Kein Blick in die Zukunft
# --------------------------------------------------------------------------


def test_features_do_not_look_ahead(ohlcv, strategy):
    """
    Merkmale an einem Zeitpunkt dürfen sich nicht ändern, wenn später weitere
    Kerzen dazukommen. Das ist der Test, an dem Lookahead-Bias scheitert.
    """
    cut = CANDLES - 200

    full = build_features(strategy, ohlcv)
    truncated = build_features(strategy, ohlcv.iloc[:cut].copy())

    compared = 0
    for col in feature_columns(full):
        a = full[col].iloc[STARTUP:cut].to_numpy(dtype=float)
        b = truncated[col].iloc[STARTUP:cut].to_numpy(dtype=float)
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12, err_msg=f"Lookahead in {col}")
        compared += 1

    assert compared >= 15, "Es wurden kaum Merkmale geprüft — stimmt der Aufbau noch?"


def test_target_does_look_ahead(ohlcv, strategy):
    """
    Gegenprobe: die Zielgröße *muss* in die Zukunft greifen, sonst wäre sie
    kein Vorhersageziel. Am Ende des Verlaufs fehlt sie deshalb.
    """
    horizon = 24
    df = strategy.set_freqai_targets(ohlcv.copy(), {})
    assert df["&-s_close"].iloc[-horizon:].isna().all()
    assert df["&-s_close"].iloc[STARTUP:-horizon].notna().all()


def test_target_is_volatility_scaled(ohlcv, strategy):
    """
    Die Zielgröße ist eine Rendite geteilt durch eine Volatilität, also eine
    dimensionslose Zahl in der Größenordnung einzelner Standardabweichungen.
    """
    df = strategy.set_freqai_targets(ohlcv.copy(), {})
    target = df["&-s_close"].iloc[STARTUP:-24]
    assert target.abs().median() < 3
    assert target.std() > 0


# --------------------------------------------------------------------------
# Brauchbarkeit für das Modell
# --------------------------------------------------------------------------


def test_no_nan_or_inf_after_startup(ohlcv, strategy):
    """Nach der Aufwärmphase darf kein Merkmal mehr NaN oder unendlich sein."""
    df = build_features(strategy, ohlcv)
    tail = df[feature_columns(df)].iloc[STARTUP:]

    nan_cols = tail.columns[tail.isna().any()].tolist()
    assert not nan_cols, f"NaN nach Aufwärmphase in: {nan_cols}"

    inf_cols = tail.columns[np.isinf(tail.to_numpy(dtype=float)).any(axis=0)].tolist()
    assert not inf_cols, f"Unendliche Werte in: {inf_cols}"


def test_features_are_not_constant(ohlcv, strategy):
    """Ein Merkmal ohne Streuung trägt nichts bei und zeigt meist einen Fehler an."""
    df = build_features(strategy, ohlcv)
    tail = df[feature_columns(df)].iloc[STARTUP:]
    flat = [c for c in tail.columns if tail[c].std() < EPS]
    assert not flat, f"Konstante Merkmale: {flat}"


def test_startup_covers_longest_window(strategy):
    """
    Die Aufwärmphase muss das längste Fenster abdecken — sonst rechnet die
    Strategie im Livebetrieb mit unvollständigen Fenstern.
    """
    strat = RealizedVolStrategy
    week_candles = 7 * 24 * 60 // 5
    assert strat.startup_candle_count >= week_candles
