"""Standalone, observational short-covering filter.

This module only analyses supplied option-chain snapshots. It never places orders,
changes strategy eligibility, or imports broker/service code.
"""
from __future__ import annotations

import logging
from typing import Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

KEYS = ["Strike", "Type"]
CURRENT_COLUMNS = ["OI", "LTP", "Volume"]
HISTORICAL_COLUMNS = ["OI", "LTP", "Volume"]


class ShortCoveringFilter:
    """Detect option contracts showing price expansion with falling OI/volume support.

    OI reference:
      * Prefer a current-snapshot previous-OI field (Prev_OI / OI_Prev).
      * Otherwise compare with the supplied historical OI moving average.
        The output labels this as a baseline deviation, not an intraday OI change.

    Input frames must contain unique Strike/Type pairs and positive historical
    baselines. Invalid rows are retained with Signal=False and a reason.
    """

    def __init__(
        self,
        oi_drop_threshold: float = -15.0,
        price_spike_threshold: float = 20.0,
        volume_multiplier: float = 2.5,
    ) -> None:
        if not np.isfinite(oi_drop_threshold) or oi_drop_threshold >= 0:
            raise ValueError("oi_drop_threshold must be a finite negative percentage")
        if not np.isfinite(price_spike_threshold) or price_spike_threshold < 0:
            raise ValueError("price_spike_threshold must be finite and non-negative")
        if not np.isfinite(volume_multiplier) or volume_multiplier <= 0:
            raise ValueError("volume_multiplier must be finite and positive")
        self.oi_drop_threshold = float(oi_drop_threshold)
        self.price_spike_threshold = float(price_spike_threshold)
        self.volume_multiplier = float(volume_multiplier)

    @staticmethod
    def _prepare(
        frame: pd.DataFrame,
        suffix: str,
        required: Iterable[str],
        label: str,
    ) -> pd.DataFrame:
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"{label} must be a pandas DataFrame")
        missing = [c for c in [*KEYS, *required] if c not in frame.columns]
        if missing:
            raise ValueError(f"{label} missing columns: {missing}")
        out = frame.copy()
        if out[KEYS].isna().any().any():
            raise ValueError(f"{label} contains missing Strike/Type keys")
        out["Strike"] = pd.to_numeric(out["Strike"], errors="coerce")
        if out["Strike"].isna().any() or not np.isfinite(out["Strike"]).all():
            raise ValueError(f"{label} contains invalid Strike values")
        out["Type"] = out["Type"].astype(str).str.upper().str.strip()
        if not out["Type"].isin(["CE", "PE"]).all():
            raise ValueError(f"{label} Type must contain only CE or PE")
        if out.duplicated(KEYS).any():
            dupes = out.loc[out.duplicated(KEYS, keep=False), KEYS].to_dict("records")
            raise ValueError(f"{label} contains duplicate Strike/Type keys: {dupes[:5]}")
        rename = {c: f"{c}_{suffix}" for c in required}
        return out.rename(columns=rename)

    def analyze_option_chain(
        self,
        df_current: pd.DataFrame,
        df_historical_ma: pd.DataFrame,
    ) -> pd.DataFrame:
        current = self._prepare(
            df_current, "curr", CURRENT_COLUMNS, "df_current"
        )
        historical = self._prepare(
            df_historical_ma, "ma", HISTORICAL_COLUMNS, "df_historical_ma"
        )

        # Preserve optional previous OI when it is available in the current feed.
        snapshot_prev_col = next(
            (c for c in ("OI_Prev_Snapshot", "prev_oi_snapshot") if c in current.columns),
            None,
        )
        session_prev_col = next(
            (c for c in ("Prev_OI", "OI_Prev", "prev_oi") if c in current.columns),
            None,
        )
        prev_col = snapshot_prev_col or session_prev_col
        previous_oi_kind = (
            "previous_snapshot" if snapshot_prev_col
            else "previous_session" if session_prev_col
            else "historical_ma"
        )
        if prev_col:
            current = current.rename(columns={prev_col: "OI_prev"})

        merged = current.merge(
            historical,
            on=KEYS,
            how="left",
            validate="one_to_one",
            indicator=True,
        )
        merged["Data_Quality"] = "OK"
        merged.loc[merged["_merge"] != "both", "Data_Quality"] = "NO_HISTORICAL_MATCH"
        merged = merged.drop(columns=["_merge"])

        numeric_cols = [
            "OI_curr", "LTP_curr", "Volume_curr",
            "OI_ma", "LTP_ma", "Volume_ma",
        ]
        for col in numeric_cols:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
            merged.loc[~np.isfinite(merged[col]), col] = np.nan

        # Prefer a genuine current-vs-previous OI reading; clearly label fallback.
        if "OI_prev" in merged.columns:
            merged["OI_prev"] = pd.to_numeric(merged["OI_prev"], errors="coerce")
            valid_prev = merged["OI_prev"].gt(0) & np.isfinite(merged["OI_prev"])
        else:
            merged["OI_prev"] = np.nan
            valid_prev = pd.Series(False, index=merged.index)

        # Upstox prev_oi / Previous OI is a previous-session reference,
        # not a prior intraday poll. Only explicitly named snapshot fields
        # can support an intraday short-covering signal.
        if previous_oi_kind == "previous_snapshot":
            merged["OI_Reference"] = np.where(valid_prev, "previous_snapshot", "invalid_previous_oi")
            merged["OI_Reference_Value"] = merged["OI_prev"]
        elif previous_oi_kind == "previous_session":
            merged["OI_Reference"] = np.where(valid_prev, "previous_session_oi", "invalid_previous_oi")
            merged["OI_Reference_Value"] = merged["OI_prev"]
        else:
            merged["OI_Reference"] = "historical_ma"
            merged["OI_Reference_Value"] = merged["OI_ma"]

        def pct_change(now: pd.Series, base: pd.Series) -> pd.Series:
            valid = now.notna() & base.notna() & now.ge(0) & base.gt(0)
            result = pd.Series(np.nan, index=merged.index, dtype=float)
            result.loc[valid] = (now.loc[valid] - base.loc[valid]) / base.loc[valid] * 100.0
            return result

        merged["OI_Pct_Change"] = pct_change(
            merged["OI_curr"], merged["OI_Reference_Value"]
        )
        merged["Price_Pct_Change"] = pct_change(
            merged["LTP_curr"], merged["LTP_ma"]
        )

        volume_valid = (
            merged["Volume_curr"].notna()
            & merged["Volume_curr"].ge(0)
            & merged["Volume_ma"].notna()
            & merged["Volume_ma"].gt(0)
        )
        merged["Volume_Ratio"] = np.nan
        merged.loc[volume_valid, "Volume_Ratio"] = (
            merged.loc[volume_valid, "Volume_curr"]
            / merged.loc[volume_valid, "Volume_ma"]
        )

        missing_or_invalid = (
            merged["OI_curr"].isna()
            | merged["LTP_curr"].isna()
            | merged["Volume_curr"].isna()
            | merged["OI_Reference_Value"].isna()
            | merged["LTP_ma"].isna()
            | merged["Volume_ma"].isna()
            | merged["OI_Reference_Value"].le(0)
            | merged["OI_curr"].lt(0)
            | merged["Volume_curr"].lt(0)
            | merged["LTP_ma"].le(0)
            | merged["Volume_ma"].le(0)
            | merged["LTP_curr"].le(0)
        )
        merged.loc[missing_or_invalid & merged["Data_Quality"].eq("OK"), "Data_Quality"] = "INVALID_OR_MISSING_BASELINE"

        # A historical moving-average deviation is not proof of intraday OI
        # reduction. Keep it visible as a candidate, but only emit Signal=True
        # when a valid previous-snapshot OI reference exists.
        common_conditions = (
            merged["Data_Quality"].eq("OK")
            & merged["OI_Pct_Change"].le(self.oi_drop_threshold)
            & merged["Price_Pct_Change"].ge(self.price_spike_threshold)
            & merged["Volume_Ratio"].ge(self.volume_multiplier)
        )
        merged["Baseline_Candidate"] = common_conditions.fillna(False).astype(bool)
        merged["Signal"] = (
            merged["Baseline_Candidate"]
            & merged["OI_Reference"].eq("previous_snapshot")
        )

        merged["Signal_Reason"] = np.select(
            [
                merged["Signal"],
                merged["Baseline_Candidate"] & merged["OI_Reference"].eq("previous_session_oi"),
                merged["Baseline_Candidate"],
            ],
            [
                "PRICE_UP_INTRADAY_OI_DOWN_VOLUME_EXPANSION",
                "PREVIOUS_SESSION_BASELINE_CANDIDATE_ONLY",
                "HISTORICAL_BASELINE_CANDIDATE_ONLY",
            ],
            default="NO_SIGNAL",
        )
        merged["Signal_Interpretation"] = np.select(
            [
                merged["Signal"],
                merged["Baseline_Candidate"] & merged["OI_Reference"].eq("previous_session_oi"),
                merged["Baseline_Candidate"],
            ],
            [
                "INTRADAY_OI_REDUCTION_EVIDENCE",
                "PREVIOUS_SESSION_OI_BASELINE_ONLY",
                "HISTORICAL_OI_BASELINE_DEVIATION_ONLY",
            ],
            default="NOT_CONFIRMED",
        )

        logger.info(
            "Short-covering analysis complete: %d contracts, %d observational signals",
            len(merged),
            int(merged["Signal"].sum()),
        )
        return merged
