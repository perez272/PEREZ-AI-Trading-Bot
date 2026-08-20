# Independent Telegram Service

This service keeps Telegram status/control available when the EC2 trading instance is stopped.

## Architecture

- EC2 PEREZ AI publishes heartbeat, forecast and trade-status events to an independent HTTPS endpoint.
- The independent service stores the latest state in DynamoDB.
- Telegram commands are handled by the independent service and do not require EC2 to be running.
- The service never contains Angel One credentials and never places trades.
- When EC2 stops publishing, the service reports the trading engine as OFFLINE/STALE rather than fabricating live data.

## Required AWS resources

- API Gateway HTTPS API
- Lambda function
- DynamoDB table for state
- Secrets Manager secret containing the Telegram bot token
- Optional EventBridge schedule for stale-state checks

The infrastructure template is intentionally separated from the EC2 trading service so the Telegram layer can remain available independently.
