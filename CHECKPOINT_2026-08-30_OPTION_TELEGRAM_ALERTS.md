# PEREZ AI Checkpoint — 2026-08-30

## Telegram option alert format

Paper-trade candidate alerts now expose the exact human-readable option contract in the headline:

`NIFTY 10 SEP 25800 CE`

or

`NIFTY 10 SEP 25800 PE`

The alert also exposes:
- option score
- underlying score
- CE/PE signal
- entry price
- quantity
- stop loss
- target
- evidence-based reason
- explicit paper-only/live-orders-disabled status

Exit alerts use the same human-readable contract format.

## Safety
- Paper trading only.
- Live orders remain disabled.
- This checkpoint changes Telegram presentation only; it does not bypass option/risk gates or hard-code a strike.

## Repository
- Branch: `main`
- Commit: `be31106632e300b866a4178ffaaefc6321ff1d02`
- Previous Telegram alert commit: `3a074f2a025eb01dccaed06e0b4c7a7fb33efed6`

## Runtime context from latest user-provided snapshot
- Runtime: ONLINE
- Mode: PAPER TRADING ONLY
- Live orders: DISABLED
- Market-data mode: auto
- Upstox enabled/configured: YES
- Market session: waiting_for_market_session
- Next entry window: 2026-08-31 09:15 IST
- Closed paper trades: 0
- Market observations: 12070
- Lessons/events: 2352
- Option surge events: 1029
- Outcome learning: waiting for first closed trade
- Pattern learning: ready
