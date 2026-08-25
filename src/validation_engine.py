"""Out-of-sample and risk-quality metrics for paper-trading validation."""


def summarize_outcomes(outcomes):
    rows = list(outcomes or [])
    n = len(rows)
    if not n:
        return {"trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0, "max_drawdown": 0.0}

    pnls = [float(r.get("pnl", 0) or 0) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    equity = peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "trades": n,
        "win_rate": round(len(wins) / n * 100, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else (999.0 if gross_win else 0.0),
        "expectancy": round(sum(pnls) / n, 4),
        "max_drawdown": round(max_dd, 4),
    }


def validation_status(stats, minimum_trades=30):
    if stats["trades"] < minimum_trades:
        return "COLLECTING_EVIDENCE"
    if stats["profit_factor"] > 1.15 and stats["expectancy"] > 0:
        return "PROMISING_BUT_UNPROVEN"
    return "NO_CONFIRMED_EDGE"
