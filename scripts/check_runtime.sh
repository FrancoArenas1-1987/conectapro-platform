#!/usr/bin/env bash
set -euo pipefail

missing=0

check_var() {
  local var_name="$1"
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing env var: ${var_name}"
    missing=1
  else
    echo "Found env var: ${var_name}"
  fi
}

echo "== Checking WhatsApp configuration =="
check_var "WHATSAPP_PHONE_NUMBER_ID"
check_var "WHATSAPP_ACCESS_TOKEN"
check_var "WHATSAPP_VERIFY_TOKEN"

echo "== Checking OpenAI configuration (optional) =="
if [[ -n "${OPENAI_ENABLED:-}" && "${OPENAI_ENABLED}" != "0" ]]; then
  check_var "OPENAI_API_KEY"
  check_var "OPENAI_MODEL"
else
  echo "OPENAI_ENABLED not set or 0: skipping OpenAI validation."
fi

echo "== Checking DB configuration =="
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "Missing env var: DATABASE_URL"
  missing=1
else
  echo "Found env var: DATABASE_URL"
fi

if [[ $missing -ne 0 ]]; then
  echo "Runtime checks failed."
  exit 1
fi

echo "Runtime checks passed."
