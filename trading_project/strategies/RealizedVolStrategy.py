"""
Realized-Volatility-Features für FreqAI.

Setzt die Messgrößen der Realized-Volatility-Literatur (Andersen/Bollerslev,
Barndorff-Nielsen/Shephard, Corsi) auf OHLCV-Kerzen um und gibt sie als
Merkmale an FreqAI. Alle Merkmale blicken ausschließlich zurück; nur die
Zielgröße in `set_freqai_targets` greift in die Zukunft.

Die Messgrößen im Einzelnen:

* Realized Variance    RV = Σ r²              — Gesamtschwankung im Fenster
* Realized Semivariance RS± = Σ r²·1{r≷0}     — getrennte gute/schlechte Schwankung
* Bipower Variation    BV = π/2 · Σ|r_{t-1}||r_t|  — sprungrobuster Teil von RV
* Sprungkomponente     J  = max(RV − BV, 0)   — der Rest, also die Sprünge
* Realized Skew/Kurt   normierte 3./4. Momente der Renditen
* HAR-Struktur         RV über Stunde, Tag und Woche (Corsi 2009)

Die Zielgröße ist die vorwärtsgerichtete Rendite, geteilt durch die zum
Zeitpunkt der Vorhersage bekannte Volatilität. Das Modell sagt also
Bewegung in Einheiten der eigenen Schwankungsbreite voraus, nicht in Prozent
— die Idee der volatilitätsskalierten Zielgröße aus den Arbeiten zu
Deep Momentum Networks.

Hinweis: Dies ist ein Merkmalsgerüst, keine geprüfte Handelsstrategie. Vor
jedem Einsatz gehören `freqtrade lookahead-analysis` und
`freqtrade recursive-analysis` darüber.
"""

import logging
from functools import reduce

import numpy as np
from pandas import DataFrame, Series

from freqtrade.exchange import timeframe_to_minutes
from freqtrade.strategy import IStrategy


logger = logging.getLogger(__name__)

EPS = 1e-12


def log_returns(close: Series) -> Series:
    """Logarithmische Rendite von Kerze zu Kerze."""
    return np.log(close / close.shift(1))


def realized_variance(r: Series, window: int) -> Series:
    """Realized Variance: Summe der quadrierten Renditen im Fenster."""
    return r.pow(2).rolling(window).sum()


def realized_semivariance(r: Series, window: int) -> tuple[Series, Series]:
    """
    Zerlegt die Realized Variance in den Anteil steigender und fallender Kerzen.

    `clip` erhält fehlende Renditen als NaN — mit `where` würde die erste,
    undefinierte Rendite zu einer echten Null und die beiden Hälften ergäben
    zusammen nicht mehr exakt die Realized Variance.
    """
    up = r.clip(lower=0).pow(2).rolling(window).sum()
    down = r.clip(upper=0).pow(2).rolling(window).sum()
    return up, down


def bipower_variation(r: Series, window: int) -> Series:
    """
    Bipower Variation nach Barndorff-Nielsen/Shephard.

    Das Produkt benachbarter Absolutrenditen bleibt von einzelnen Sprüngen
    weitgehend unberührt, schätzt also den stetigen Teil der Schwankung.
    """
    return (np.pi / 2) * (r.abs() * r.abs().shift(1)).rolling(window).sum()


def realized_skew(r: Series, window: int, rv: Series) -> Series:
    """Auf die Realized Variance normierte dritte Moment der Renditen."""
    n = window
    return np.sqrt(n) * r.pow(3).rolling(window).sum() / (rv.pow(1.5) + EPS)


def realized_kurtosis(r: Series, window: int, rv: Series) -> Series:
    """Auf die Realized Variance normierte vierte Moment der Renditen."""
    n = window
    return n * r.pow(4).rolling(window).sum() / (rv.pow(2) + EPS)


class RealizedVolStrategy(IStrategy):
    """FreqAI-Strategie auf Basis von Realized-Volatility-Merkmalen."""

    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short = False

    minimal_roi = {"0": 0.05, "240": 0.02, "720": 0}
    stoploss = -0.05
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True

    # Das längste Fenster ist die HAR-Woche; dazu Reserve für die Rollfenster.
    startup_candle_count: int = 2100

    # Einstiegs- und Ausstiegsschwelle in Einheiten der Standardabweichung,
    # passend zur volatilitätsskalierten Zielgröße.
    entry_sigma = 0.5
    exit_sigma = -0.1

    plot_config = {
        "main_plot": {},
        "subplots": {
            "&-s_close": {"&-s_close": {"color": "#156c9b"}},
            "do_predict": {"do_predict": {"color": "#8a6310"}},
        },
    }

    def _candles(self, minutes: int) -> int:
        """Anzahl Kerzen, die der angegebenen Zeitspanne entsprechen."""
        return max(2, int(minutes / timeframe_to_minutes(self.timeframe)))

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Die Realized-Messgrößen über die in `indicator_periods_candles`
        konfigurierten Fensterlängen.
        """
        r = log_returns(dataframe["close"])

        rv = realized_variance(r, period)
        up, down = realized_semivariance(r, period)
        bv = bipower_variation(r, period)
        jump = (rv - bv).clip(lower=0)

        # Volatilität statt Varianz: gleiche Größenordnung wie Renditen.
        dataframe["%-rvol-period"] = np.sqrt(rv)

        # Vorzeichenasymmetrie: Anteil der Abwärtsschwankung an der Gesamtschwankung.
        # 0.5 heißt symmetrisch, darüber überwiegt die schlechte Volatilität.
        dataframe["%-downside_share-period"] = down / (rv + EPS)

        # Signed Jump Variation: positive Sprünge minus negative Sprünge.
        dataframe["%-signed_jump-period"] = (up - down) / (rv + EPS)

        # Anteil der Sprünge an der Gesamtschwankung.
        dataframe["%-jump_share-period"] = jump / (rv + EPS)

        # Sprungrobuste Volatilität.
        dataframe["%-bpvol-period"] = np.sqrt(bv)

        # Form der Renditeverteilung im Fenster.
        dataframe["%-rskew-period"] = realized_skew(r, period, rv)
        dataframe["%-rkurt-period"] = realized_kurtosis(r, period, rv)

        # Volatilität der Volatilität.
        dataframe["%-vol_of_vol-period"] = (
            np.sqrt(rv).rolling(period).std() / (np.sqrt(rv) + EPS)
        )

        # Wo steht der Preis innerhalb seiner jüngsten Spanne?
        low = dataframe["low"].rolling(period).min()
        high = dataframe["high"].rolling(period).max()
        dataframe["%-range_position-period"] = (dataframe["close"] - low) / (high - low + EPS)

        # Volumen relativ zum eigenen Mittel.
        dataframe["%-relative_volume-period"] = dataframe["volume"] / (
            dataframe["volume"].rolling(period).mean() + EPS
        )

        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """Merkmale ohne eigene Fensterlänge."""
        r = log_returns(dataframe["close"])
        dataframe["%-log_return"] = r
        dataframe["%-abs_return"] = r.abs()

        # Garman-Klass: nutzt Hoch, Tief und Eröffnung statt nur Schlusskurse
        # und schätzt die Schwankung einer einzelnen Kerze deutlich genauer.
        hl = np.log(dataframe["high"] / (dataframe["low"] + EPS)).pow(2)
        co = np.log(dataframe["close"] / (dataframe["open"] + EPS)).pow(2)
        dataframe["%-gk_vol"] = np.sqrt((0.5 * hl - (2 * np.log(2) - 1) * co).clip(lower=0))

        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """
        Die HAR-Struktur und die Fristigkeit der Volatilität.

        Das HAR-Modell erklärt die Volatilität von morgen aus der Volatilität
        der vergangenen Stunde, des vergangenen Tages und der vergangenen
        Woche. Die drei Horizonte zusammen bilden ab, dass kurzfristig und
        langfristig orientierte Marktteilnehmer unterschiedlich reagieren.
        """
        r = log_returns(dataframe["close"])

        h = self._candles(60)
        d = self._candles(60 * 24)
        w = self._candles(60 * 24 * 7)

        rv_h = np.sqrt(realized_variance(r, h))
        rv_d = np.sqrt(realized_variance(r, d))
        rv_w = np.sqrt(realized_variance(r, w))

        dataframe["%-har_hour"] = rv_h
        dataframe["%-har_day"] = rv_d
        dataframe["%-har_week"] = rv_w

        # Fristigkeit: liegt die kurzfristige Schwankung über oder unter der
        # langfristigen? Werte über 1 zeigen eine aufziehende Phase an.
        dataframe["%-term_hour_day"] = rv_h / (rv_d + EPS)
        dataframe["%-term_day_week"] = rv_d / (rv_w + EPS)

        # Saisonalität: Kryptomärkte haben eine stabile Tagesstruktur.
        dataframe["%-hour_of_day"] = dataframe["date"].dt.hour
        dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek

        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """
        Zielgröße: vorwärtsgerichtete Rendite, geteilt durch die zum
        Vorhersagezeitpunkt bekannte Volatilität.

        Die Division macht die Zielgröße über ruhige und turbulente Phasen
        hinweg vergleichbar — ein Prozent Bewegung wiegt in einer ruhigen
        Phase schwerer als in einer hektischen.
        """
        horizon = int(self.freqai_info["feature_parameters"]["label_period_candles"])

        r = log_returns(dataframe["close"])
        # Volatilität aus der Vergangenheit, Stand jetzt — kein Blick nach vorn.
        sigma = np.sqrt(realized_variance(r, horizon))

        forward = dataframe["close"].shift(-horizon) / dataframe["close"] - 1

        dataframe["&-s_close"] = forward / (sigma + EPS)

        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        conditions = [
            df["do_predict"] == 1,
            df["&-s_close"] > self.entry_sigma,
            df["volume"] > 0,
        ]
        df.loc[reduce(lambda x, y: x & y, conditions), ["enter_long", "enter_tag"]] = (
            1,
            "rv_long",
        )
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        conditions = [
            df["do_predict"] == 1,
            df["&-s_close"] < self.exit_sigma,
        ]
        df.loc[reduce(lambda x, y: x & y, conditions), ["exit_long", "exit_tag"]] = (
            1,
            "rv_exit",
        )
        return df
