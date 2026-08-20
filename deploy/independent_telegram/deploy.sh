#!/usr/bin/env bash
set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION}"
: "${TELEGRAM_TOKEN_SECRET_ARN:?Set TELEGRAM_TOKEN_SECRET_ARN}"
: "${TELEGRAM_CHAT_ID:?Set TELEGRAM_CHAT_ID}"
: "${REMOTE_STATUS_TOKEN:?Set REMOTE_STATUS_TOKEN}"
: "${STACK_NAME:=perez-ai-telegram-independent}"

ROOT="$(cd "$(dirname "$0")" && pwd)"

sam build --template-file "$ROOT/infrastructure/template.yaml"
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    TelegramTokenSecretArn="$TELEGRAM_TOKEN_SECRET_ARN" \
    TelegramChatId="$TELEGRAM_CHAT_ID" \
    RemoteStatusToken="$REMOTE_STATUS_TOKEN" \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset

echo "Deployment complete."
sam list stack-outputs --stack-name "$STACK_NAME" --region "$AWS_REGION"
