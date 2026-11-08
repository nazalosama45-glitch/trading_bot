"""
SafetyGuard: checks market conditions before every trade.
Blocks or reduces position size when conditions look dangerous.
"""
import logging
import pandas as pd
import numpy as np
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class GuardResult:
    allowed: bool
    size_multiplier: float   # 0.0 = block, 0.5 = half size, 1.0 = full size
    reason: str


class SafetyGuard:
    def __init__(self):
        self.consecutive_losses: int = 0
        self.last_5_trades: list = []   # list of True/False (win/loss)

    def register_trade_result(self, profitable: bool):
        self.last_5_trades.append(profitable)
        if len(self.last_5_trades) > 5:
            self.last_5_trades.pop(0)
        if not profitable:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def check(self, df: pd.DataFrame, signal_confidence: float) -> GuardResult:
        """
        Run all safety checks. Returns GuardResult.
        df = enriched dataframe (after compute_all)
        """
        checks = [
            self._check_consecutive_losses(),
            self._check_market_regime(df),
            self._check_volatility_spike(df),
            self._check_confidence(signal_confidence),
            self._check_recent_loss_rate(),
        ]

        # Find the most restrictive result
        for result in checks:
            if not result.allowed:
                logger.warning(f"Trade blocked by SafetyGuard: {result.reason}")
                return result

        # Apply the smallest multiplier among all checks
        min_mult = min(r.size_multiplier for r in checks)
        if min_mult < 1.0:
            reason = " | ".join(r.reason for r in checks if r.size_multiplier < 1.0)
            logger.info(f"SafetyGuard: reduced size to {min_mult:.0%} — {reason}")
            return GuardResult(allowed=True, size_multiplier=min_mult, reason=reason)

        return GuardResult(allowed=True, size_multiplier=1.0, reason="all clear")

    # ── Individual checks ──────────────────────────────────────────────────────

    def _check_consecutive_losses(self) -> GuardResult:
        """Back off hard after a losing streak."""
        if self.consecutive_losses >= 4:
            return GuardResult(False, 0.0, f"{self.consecutive_losses} consecutive losses — pausing")
        if self.consecutive_losses == 3:
            return GuardResult(True, 0.25, "3 consecutive losses — quarter size")
        if self.consecutive_losses == 2:
            return GuardResult(True, 0.5, "2 consecutive losses — half size")
        return GuardResult(True, 1.0, "")

    def _check_recent_loss_rate(self) -> GuardResult:
        """If 4 of last 5 trades lost, reduce size."""
        if len(self.last_5_trades) >= 5:
            loss_rate = self.last_5_trades.count(False) / len(self.last_5_trades)
            if loss_rate >= 0.8:
                return GuardResult(True, 0.5, f"high recent loss rate ({loss_rate:.0%})")
        return GuardResult(True, 1.0, "")

    def _check_market_regime(self, df: pd.DataFrame) -> GuardResult:
        """
        Detect choppy/sideways market using ADX-like logic.
        In choppy markets trend-following strategies lose.
        """
        if len(df) < 20:
            return GuardResult(True, 1.0, "")

        close = df["close"]

        # Measure how directional recent price action is
        # High std of returns relative to range = choppy
        last20 = close.iloc[-20:]
        price_range = (last20.max() - last20.min()) / last20.mean()
        returns = last20.pct_change().dropna()
        volatility = returns.std()

        # Choppiness index: low = trending, high = ranging
        choppiness = volatility / (price_range + 1e-9)

        if choppiness > 0.08:
            return GuardResult(False, 0.0, f"choppy market detected (choppiness={choppiness:.3f})")
        if choppiness > 0.05:
            return GuardResult(True, 0.5, f"mildly choppy market ({choppiness:.3f})")

        return GuardResult(True, 1.0, "")

    def _check_volatility_spike(self, df: pd.DataFrame) -> GuardResult:
        """
        Block trades during extreme volatility spikes (e.g. news events, flash crashes).
        Current ATR vs average ATR.
        """
        if "atr" not in df.columns or len(df) < 20:
            return GuardResult(True, 1.0, "")

        current_atr = df["atr"].iloc[-1]
        avg_atr = df["atr"].iloc[-20:].mean()

        if avg_atr == 0:
            return GuardResult(True, 1.0, "")

        atr_ratio = current_atr / avg_atr

        if atr_ratio > 3.0:
            return GuardResult(False, 0.0, f"extreme volatility spike (ATR {atr_ratio:.1f}x normal)")
        if atr_ratio > 2.0:
            return GuardResult(True, 0.5, f"elevated volatility (ATR {atr_ratio:.1f}x normal)")

        return GuardResult(True, 1.0, "")

    def _check_confidence(self, confidence: float) -> GuardResult:
        """Require minimum confidence. Scale size with confidence."""
        if confidence < 0.55:
            return GuardResult(False, 0.0, f"confidence too low ({confidence:.2f})")
        if confidence < 0.65:
            return GuardResult(True, 0.5, f"moderate confidence ({confidence:.2f})")
        if confidence < 0.75:
            return GuardResult(True, 0.75, f"good confidence ({confidence:.2f})")
        return GuardResult(True, 1.0, "")
