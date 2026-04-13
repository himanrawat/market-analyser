"""Four bucket scorers implementing PRD sections F-3.1 through F-3.4.

Each class:
  1. Computes per-factor scores using primitives from base.py
  2. Checks disqualifiers (hard fail conditions from the PRD)
  3. Returns a ScoreOutput with breakdown for explainability (F-7.8, F-7.9)

Weights are passed in at call time from config/weights.yaml (or overridden
per-user via settings_kv). This keeps the scorer pure and testable.
"""
from __future__ import annotations

from pipeline.db.enums import Bucket, Country
from pipeline.scoring.base import (
    ScoreOutput,
    StockData,
    compute_cagr,
    scale,
    score_above_dma,
    score_bank_asset_quality,
    score_cagr,
    score_debt_equity,
    score_delivery_pct,
    score_distance_from_high,
    score_dma_crossover,
    score_earnings_beat,
    score_fcf,
    score_fii_trend,
    score_nim,
    score_pcr,
    score_pe_vs_own_history,
    score_pe_vs_sector,
    score_promoter_holding_stable,
    score_promoter_pledge,
    score_roe,
    score_rsi,
    score_sales_growth,
    score_volume_trend,
)

# ---------------------------------------------------------------------------
# Default weights (loaded from config/weights.yaml at runtime; these are
# fallbacks used in tests so we don't need the file on disk)
# ---------------------------------------------------------------------------

_DEFAULT_QV = {
    "roe_5yr_avg": 15,
    "debt_equity": 10,
    "earnings_growth_5yr_cagr": 10,
    "fcf_positive_growing": 10,
    "pe_vs_sector_median": 15,
    "pe_vs_own_5yr_median": 10,
    "dividend_yield": 5,
    "promoter_holding_stable": 5,
    # India-only factors (applied when country == INDIA; weight taken from bucket total)
    "promoter_pledge": 5,
    "fii_trend": 5,
    "delivery_pct": 5,
    "bank_asset_quality": 5,   # banks/NBFCs only
    "bank_nim": 5,             # banks/NBFCs only
}

_DEFAULT_MOM = {
    "momentum_12m_1m": 25,
    "above_200dma": 10,
    "dma_50_above_200": 10,
    "distance_from_52wk_high": 10,
    "volume_trend": 10,
    "earnings_beat": 10,
    "sales_growth_latest_qtr": 15,
    "rsi_14": 10,
    # India-only overlays
    "delivery_pct": 5,
    "pcr_signal": 5,
}

_DEFAULT_QM = {
    "roe_5yr_avg": 15,
    "debt_equity": 10,
    "earnings_growth_3yr_cagr": 15,
    "fcf_positive_growing": 10,
    "momentum_12m_1m": 20,
    "above_200dma": 10,
    "dma_50_above_200": 10,
    "distance_from_52wk_high": 10,
}

_DEFAULT_DG = {
    "consecutive_dividend_years": 25,
    "dividend_growth_5yr_cagr": 20,
    "dividend_yield": 15,
    "payout_ratio": 15,
    "fcf_coverage_of_dividend": 15,
    "earnings_stability": 10,
}


# ---------------------------------------------------------------------------
# F-3.1 Quality + Value
# ---------------------------------------------------------------------------


def _prepare_qv_inputs(f: list[dict], sector: str | None) -> dict:
    """Extract and derive all values QualityValueScorer needs from fundamentals."""
    latest_pe = f[0].get("pe") if f else None
    latest_div_yield = f[0].get("dividend_yield") if f else None
    promoter = f[0].get("promoter_holding") if f else None
    de = f[0].get("debt_equity") if f else None
    if _is_financial_sector(sector):
        de = None  # D/E excluded for banks/NBFCs per PRD
    roes = [q.get("roe") for q in f[:20]]
    eps_values = [q.get("eps") for q in f[:21]]
    eps_cagr = compute_cagr(eps_values, periods_per_year=4)
    if eps_cagr is not None:
        eps_cagr *= 100
    historical_pes = [q.get("pe") for q in f[1:21] if q.get("pe")]
    margins = [q.get("net_margin") for q in f[:12] if q.get("net_margin") is not None]
    return {
        "latest_pe": latest_pe, "latest_div_yield": latest_div_yield, "promoter": promoter,
        "de": de, "roe_5yr": _avg(roes), "eps_cagr": eps_cagr,
        "historical_pes": historical_pes, "margins": margins,
    }


def _compute_qv_factors(inp: dict, data: StockData, w: dict) -> dict[str, float]:
    fs: dict[str, float] = {}
    fs["roe_5yr_avg"] = score_roe(inp["roe_5yr"], w.get("roe_5yr_avg", 0))
    fs["debt_equity"] = score_debt_equity(inp["de"], w.get("debt_equity", 0))
    fs["earnings_growth_5yr_cagr"] = score_cagr(
        inp["eps_cagr"], w.get("earnings_growth_5yr_cagr", 0), target=15.0
    )
    fs["fcf_positive_growing"] = score_fcf(data.fundamentals, w.get("fcf_positive_growing", 0))
    fs["pe_vs_sector_median"] = score_pe_vs_sector(
        inp["latest_pe"], data.sector_median_pe, w.get("pe_vs_sector_median", 0)
    )
    fs["pe_vs_own_5yr_median"] = score_pe_vs_own_history(
        inp["latest_pe"], inp["historical_pes"], w.get("pe_vs_own_5yr_median", 0)
    )
    div_yield = inp["latest_div_yield"]
    fs["dividend_yield"] = w.get("dividend_yield", 0) if (div_yield and div_yield > 1.0) else 0.0
    fs["promoter_holding_stable"] = _score_promoter(
        inp["promoter"], data.fundamentals, w.get("promoter_holding_stable", 0), data.country
    )
    # India-specific overlay factors
    if data.country == Country.INDIA:
        fs["promoter_pledge"] = score_promoter_pledge(
            data.promoter_pledge_pct, w.get("promoter_pledge", 0)
        )
        fs["fii_trend"] = score_fii_trend(
            data.fundamentals, w.get("fii_trend", 0)
        )
        fs["delivery_pct"] = score_delivery_pct(
            data.delivery_pct, w.get("delivery_pct", 0)
        )
        if _is_financial_sector(data.sector):
            latest = data.fundamentals[0] if data.fundamentals else {}
            fs["bank_asset_quality"] = score_bank_asset_quality(
                latest.get("gnpa_pct"), w.get("bank_asset_quality", 0)
            )
            fs["bank_nim"] = score_nim(
                latest.get("nim_pct"), w.get("bank_nim", 0)
            )
    return fs


def _qv_disqualifiers(inp: dict, sector_median_pe: float | None) -> list[str]:
    dq: list[str] = []
    if inp["de"] is not None and inp["de"] > 2.0:
        dq.append("high_debt (D/E > 2)")
    if _declining_margins(inp["margins"], consecutive=3):
        dq.append("declining_margins_3q")
    if inp["latest_pe"] and sector_median_pe and inp["latest_pe"] > sector_median_pe * 1.25:
        dq.append("pe_in_top_quintile_of_sector")
    return dq


class QualityValueScorer:
    bucket = Bucket.QUALITY_VALUE

    def score(
        self, data: StockData, weights: dict[str, float] | None = None
    ) -> ScoreOutput:
        w = weights or _DEFAULT_QV
        inp = _prepare_qv_inputs(data.fundamentals, data.sector)
        fs = _compute_qv_factors(inp, data, w)
        raw_score = sum(fs.values())

        dq = _qv_disqualifiers(inp, data.sector_median_pe)

        return ScoreOutput(
            ticker=data.ticker,
            country=data.country,
            bucket=self.bucket,
            score=max(0.0, raw_score),
            qualified=len(dq) == 0,
            factor_scores=fs,
            disqualifiers=dq,
        )


# ---------------------------------------------------------------------------
# F-3.2 Momentum / Trend
# ---------------------------------------------------------------------------


class MomentumScorer:
    bucket = Bucket.MOMENTUM

    def score(
        self, data: StockData, weights: dict[str, float] | None = None
    ) -> ScoreOutput:
        w = weights or _DEFAULT_MOM
        f = data.fundamentals
        price = data.latest_close

        fs: dict[str, float] = {}
        fs["momentum_12m_1m"] = _score_momentum(
            data.momentum_12m_1m, w.get("momentum_12m_1m", 0)
        )
        fs["above_200dma"] = score_above_dma(price, data.dma_200, w.get("above_200dma", 0))
        fs["dma_50_above_200"] = score_dma_crossover(
            data.dma_50, data.dma_200, w.get("dma_50_above_200", 0)
        )
        fs["distance_from_52wk_high"] = score_distance_from_high(
            price, data.high_52w, w.get("distance_from_52wk_high", 0), within_pct=15.0
        )
        fs["volume_trend"] = score_volume_trend(data.prices, w.get("volume_trend", 0))
        fs["earnings_beat"] = score_earnings_beat(f, w.get("earnings_beat", 0))
        fs["sales_growth_latest_qtr"] = score_sales_growth(
            f, w.get("sales_growth_latest_qtr", 0), target_pct=15.0
        )
        fs["rsi_14"] = score_rsi(data.rsi_14, w.get("rsi_14", 0))

        # India-specific momentum overlays
        if data.country == Country.INDIA:
            fs["delivery_pct"] = score_delivery_pct(
                data.delivery_pct, w.get("delivery_pct", 0)
            )
            fs["pcr_signal"] = score_pcr(data.put_call_ratio, w.get("pcr_signal", 0))

        raw_score = sum(fs.values())

        # --- Disqualifiers (F-3.2) ---
        dq: list[str] = []
        if price is not None and data.dma_200 is not None and price < data.dma_200:
            dq.append("below_200dma")
        if data.dma_50 is not None and data.dma_200 is not None and data.dma_50 < data.dma_200:
            dq.append("broken_trend (50dma < 200dma)")
        if f and _is_earnings_miss(f[0]):
            dq.append("recent_earnings_miss")

        return ScoreOutput(
            ticker=data.ticker,
            country=data.country,
            bucket=self.bucket,
            score=max(0.0, raw_score),
            qualified=len(dq) == 0,
            factor_scores=fs,
            disqualifiers=dq,
        )


# ---------------------------------------------------------------------------
# F-3.3 Quality + Momentum (primary recommended strategy)
# ---------------------------------------------------------------------------


class QualityMomentumScorer:
    bucket = Bucket.QUALITY_MOMENTUM

    def score(
        self, data: StockData, weights: dict[str, float] | None = None
    ) -> ScoreOutput:
        w = weights or _DEFAULT_QM
        f = data.fundamentals
        price = data.latest_close

        roes = [q.get("roe") for q in f[:20]]
        roe_5yr = _avg(roes)
        de = f[0].get("debt_equity") if f else None
        if _is_financial_sector(data.sector):
            de = None

        eps_3yr = [q.get("eps") for q in f[:13]]
        eps_cagr_3yr = compute_cagr(eps_3yr, periods_per_year=4)
        if eps_cagr_3yr is not None:
            eps_cagr_3yr *= 100

        fs: dict[str, float] = {}
        fs["roe_5yr_avg"] = score_roe(roe_5yr, w.get("roe_5yr_avg", 0), low_threshold=8.0)
        fs["debt_equity"] = score_debt_equity(de, w.get("debt_equity", 0), max_de=1.0)
        fs["earnings_growth_3yr_cagr"] = score_cagr(
            eps_cagr_3yr, w.get("earnings_growth_3yr_cagr", 0), target=15.0
        )
        fs["fcf_positive_growing"] = score_fcf(f, w.get("fcf_positive_growing", 0))
        fs["momentum_12m_1m"] = _score_momentum(
            data.momentum_12m_1m, w.get("momentum_12m_1m", 0)
        )
        fs["above_200dma"] = score_above_dma(price, data.dma_200, w.get("above_200dma", 0))
        fs["dma_50_above_200"] = score_dma_crossover(
            data.dma_50, data.dma_200, w.get("dma_50_above_200", 0)
        )
        fs["distance_from_52wk_high"] = score_distance_from_high(
            price, data.high_52w, w.get("distance_from_52wk_high", 0), within_pct=20.0
        )

        raw_score = sum(fs.values())

        # Disqualifiers (F-3.3): either fundamental OR trend failure disqualifies
        dq: list[str] = []
        fundamental_fail = (
            (roe_5yr is not None and roe_5yr < 8.0)
            or (de is not None and de > 1.0)
            or (eps_cagr_3yr is not None and eps_cagr_3yr < 0)
        )
        trend_fail = (
            price is not None
            and data.dma_200 is not None
            and price < data.dma_200
        ) or (
            data.dma_50 is not None
            and data.dma_200 is not None
            and data.dma_50 < data.dma_200
        )

        if fundamental_fail:
            dq.append("fundamental_quality_failure")
        if trend_fail:
            dq.append("price_trend_failure")

        return ScoreOutput(
            ticker=data.ticker,
            country=data.country,
            bucket=self.bucket,
            score=max(0.0, raw_score),
            qualified=len(dq) == 0,
            factor_scores=fs,
            disqualifiers=dq,
        )


# ---------------------------------------------------------------------------
# F-3.4 Dividend Growth
# ---------------------------------------------------------------------------


def _prepare_dg_inputs(f: list[dict]) -> dict:
    div_yields = [q.get("dividend_yield") for q in f if q.get("dividend_yield")]
    div_per_shares = [q.get("dividend_per_share") for q in f if q.get("dividend_per_share")]
    eps_values = [q.get("eps") for q in f[:20] if q.get("eps") is not None]
    div_cagr = compute_cagr(div_per_shares[:21], periods_per_year=4)
    if div_cagr is not None:
        div_cagr *= 100
    return {
        "div_per_shares": div_per_shares,
        "latest_div_yield": div_yields[0] if div_yields else None,
        "latest_payout": f[0].get("payout_ratio") if f else None,
        "latest_fcf": f[0].get("free_cash_flow") if f else None,
        "consec_years": _count_consecutive_div_increases(div_per_shares),
        "div_cagr": div_cagr,
        "eps_values": eps_values,
        "fcf_coverage": _fcf_covers_dividend(
            f[0].get("free_cash_flow") if f else None, div_per_shares, f
        ),
    }


def _compute_dg_factors(inp: dict, country: str, w: dict) -> dict[str, float]:
    target_years = 5 if country == Country.INDIA else 10
    div_yield = inp["latest_div_yield"]
    payout = inp["latest_payout"]
    fs: dict[str, float] = {
        "consecutive_dividend_years": scale(
            inp["consec_years"], 0, target_years
        ) * w.get("consecutive_dividend_years", 0),
        "dividend_growth_5yr_cagr": scale(
            inp["div_cagr"] or 0, 0, 10
        ) * w.get("dividend_growth_5yr_cagr", 0),
        "dividend_yield": w.get("dividend_yield", 0) if (div_yield and div_yield > 1.5) else 0.0,
        "payout_ratio": (
            scale(-(payout or 100), -80, 0) * w.get("payout_ratio", 0)
            if payout is not None else 0.0
        ),
        "fcf_coverage_of_dividend": w.get("fcf_coverage_of_dividend", 0) if inp["fcf_coverage"] else 0.0,
        "earnings_stability": _earnings_stability_score(inp["eps_values"], w.get("earnings_stability", 0)),
    }
    return fs


def _dg_disqualifiers(inp: dict) -> list[str]:
    dq: list[str] = []
    if _had_dividend_cut(inp["div_per_shares"]):
        dq.append("dividend_cut_in_history")
    if inp["latest_payout"] is not None and inp["latest_payout"] > 0.80:
        dq.append("payout_ratio_too_high")
    if inp["latest_fcf"] is not None and inp["latest_fcf"] < 0:
        dq.append("negative_fcf")
    return dq


class DividendGrowthScorer:
    bucket = Bucket.DIVIDEND_GROWTH

    def score(
        self, data: StockData, weights: dict[str, float] | None = None
    ) -> ScoreOutput:
        w = weights or _DEFAULT_DG
        inp = _prepare_dg_inputs(data.fundamentals)
        fs = _compute_dg_factors(inp, data.country, w)
        raw_score = sum(fs.values())
        dq = _dg_disqualifiers(inp)

        return ScoreOutput(
            ticker=data.ticker,
            country=data.country,
            bucket=self.bucket,
            score=max(0.0, raw_score),
            qualified=len(dq) == 0,
            factor_scores=fs,
            disqualifiers=dq,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _avg(values: list) -> float | None:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _is_financial_sector(sector: str | None) -> bool:
    if not sector:
        return False
    return any(k in sector.lower() for k in ("financ", "bank", "nbfc", "insurance"))


def _declining_margins(margins: list[float], consecutive: int = 3) -> bool:
    """True if the last `consecutive` values are strictly declining."""
    if len(margins) < consecutive:
        return False
    recent = margins[:consecutive]
    return all(recent[i] > recent[i + 1] for i in range(len(recent) - 1))


def _is_earnings_miss(latest: dict) -> bool:
    eps = latest.get("eps")
    eps_est = latest.get("eps_estimate")
    if eps is None or eps_est is None or eps_est == 0:
        return False
    return (eps - eps_est) / abs(eps_est) < -0.05  # miss > 5%


def _score_momentum(momentum: float | None, full_pts: float) -> float:
    """12m-1m momentum: top quintile = full.
    Quintile threshold is computed cross-sectionally by the guardrails layer
    and injected as a pre-computed value. Here we just reward positive momentum."""
    if momentum is None:
        return 0.0
    # Positive momentum scaled up to 50% annualized → full points
    return scale(momentum, 0, 0.50) * full_pts


def _count_consecutive_div_increases(div_per_shares: list[float]) -> int:
    """Count consecutive annual increases from most-recent backwards.
    Approximate: compares quarter-averaged values year over year."""
    if len(div_per_shares) < 8:
        return 0
    # Sum into annual buckets (4 quarters)
    annual = [
        sum(div_per_shares[i * 4: (i + 1) * 4])
        for i in range(len(div_per_shares) // 4)
    ]
    count = 0
    for i in range(len(annual) - 1):
        if annual[i] > annual[i + 1]:
            count += 1
        else:
            break
    return count


def _had_dividend_cut(div_per_shares: list[float]) -> bool:
    """True if any quarter had a lower dividend than the same quarter 1yr ago."""
    if len(div_per_shares) < 8:
        return False
    return any(
        div_per_shares[i] < div_per_shares[i + 4] * 0.95
        for i in range(4)
    )


def _fcf_covers_dividend(
    fcf: float | None, div_per_shares: list[float], fundamentals: list[dict]
) -> bool:
    """FCF > 1.5× total dividends paid in the latest year."""
    if fcf is None or not div_per_shares:
        return False
    # Estimate annual div outflow: div per share × shares outstanding
    shares = fundamentals[0].get("shares_outstanding") if fundamentals else None
    if shares is None:
        # Fallback: just check FCF is positive and growing
        return fcf > 0
    annual_div = sum(div_per_shares[:4]) * shares
    return fcf > 1.5 * annual_div if annual_div > 0 else fcf > 0


def _score_promoter(
    latest: float | None, fundamentals: list[dict], full_pts: float, country: str
) -> float:
    """Promoter holding stable or rising (India only, F-3.1).
    Returns 0 for US stocks. Full pts if holding hasn't declined."""
    if country != Country.INDIA or full_pts == 0:
        return 0.0
    if latest is None:
        return 0.0
    prev = fundamentals[1].get("promoter_holding") if len(fundamentals) > 1 else None
    if prev is None:
        return full_pts * 0.5  # unknown trend → partial
    return full_pts if latest >= prev else 0.0


def _earnings_stability_score(eps_values: list[float], full_pts: float) -> float:
    """Low coefficient of variation = high stability = full points."""
    if len(eps_values) < 4:
        return 0.0
    import numpy as np
    mean = abs(float(np.mean(eps_values)))
    std = float(np.std(eps_values))
    if mean == 0:
        return 0.0
    cv = std / mean  # lower is better
    return scale(-cv, -1.0, 0.0) * full_pts  # cv=0 → full, cv>=1 → 0
