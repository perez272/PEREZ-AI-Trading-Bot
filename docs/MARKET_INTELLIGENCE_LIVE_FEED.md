# Market intelligence live feed

The read-only market intelligence page is served at `/market-intelligence` by
the existing dashboard server. Its API is `/api/market-intelligence`.

## Data source and safety

- Uses the existing authenticated Upstox market-data client.
- Reads quote snapshots and option chains only; it does not import or call order APIs.
- Does not change PEREZ's strategy, risk limits, paper/live mode, or execution path.
- Displays only symbols for which verified Upstox instrument keys are configured.
- Shows an explicit unavailable state when credentials, mappings, or quotes are missing. It never substitutes sample values into the live API response.
- Sector performance is an average of the mapped symbols returned, not official FII/DII institutional flow.
- Option OI and volume are context only. They do not identify whether buyers or writers initiated positions.

## Configure equity coverage on EC2

Keep credentials and mappings on the host, never in Git. Add verified Upstox NSE equity keys to the existing service environment, for example:

```text
UPSTOX_ENABLED=true
UPSTOX_ACCESS_TOKEN=<current token>
UPSTOX_INSTRUMENT_KEYS_JSON={"RELIANCE":"NSE_EQ|<verified instrument token>","HDFCBANK":"NSE_EQ|<verified instrument token>","INFY":"NSE_EQ|<verified instrument token>"}
PEREZ_MARKET_INTELLIGENCE_SYMBOLS=RELIANCE,HDFCBANK,INFY
```

The values above are placeholders, not usable instrument tokens. Obtain the exact keys
from the current Upstox instrument master and verify each exchange/segment.

After deployment, restart only the dashboard service, then check:

- `GET /api/market-intelligence` returns `status: LIVE` and real quote rows.
- `status: NEEDS_INSTRUMENT_MAPPING` means no verified equity keys are configured.
- `status: UNAVAILABLE` means the dashboard process cannot access Upstox credentials.
- `status: NO_QUOTES` means the configured symbols returned no valid quote data.

The endpoint refreshes every 30 seconds in the browser. Validate it during NSE market
hours before relying on the displayed values. No trading decision should be based on
this observational dashboard alone.
