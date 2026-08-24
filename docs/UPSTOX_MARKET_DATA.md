# Upstox market-data integration

PEREZ AI can use Upstox as an independent market-data source while keeping Angel One separate from market-data validation and execution.

## Environment

Set these on the EC2 host only; never commit real credentials:

```text
UPSTOX_ENABLED=true
UPSTOX_CLIENT_ID=<Upstox app client id>
UPSTOX_CLIENT_SECRET=<Upstox app client secret>
UPSTOX_ACCESS_TOKEN=<current Upstox access token>
UPSTOX_MAX_PRICE_DEVIATION_PCT=0.35
UPSTOX_INSTRUMENT_KEYS_JSON={"NIFTY":"NSE_INDEX|Nifty 50","BANKNIFTY":"NSE_INDEX|Nifty Bank"}
```

Add the exact Upstox instrument keys for every symbol that PEREZ is allowed to trade/validate. Do not guess instrument keys. Obtain them from Upstox's current instrument files/search and verify the exchange/segment before enabling validation.

## Safety behavior

When `UPSTOX_ENABLED=false`, existing behavior is unchanged.

When `UPSTOX_ENABLED=true`, a candidate is rejected if:

- the access token is missing;
- the required instrument key is missing;
- Upstox cannot return a valid closed 5-minute candle;
- Upstox data is stale/invalid; or
- the Upstox closed 5-minute close differs from the primary feed by more than `UPSTOX_MAX_PRICE_DEVIATION_PCT`.

A feed disagreement is **NO TRADE**. PEREZ never chooses the feed that makes a trade look better.

## Data endpoints

The provider uses Upstox V3 LTP and intraday candle endpoints. A future WebSocket collector can be added behind the same normalized provider interface without changing the market-integrity gate.

## Deployment

After adding credentials and mappings to the EC2 `.env`, restart the service and inspect the heartbeat/logs. Do not put the access token, client secret, or other credentials into GitHub.
