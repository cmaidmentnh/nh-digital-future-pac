#!/usr/bin/env bash
# One-shot DNS setup for digitalfuturenh.com.
# Pulls Cloudflare credentials from server.
#
# Requires:
#   - Domain already added to Cloudflare account
#   - Server SSH access
#   - jq locally
set -euo pipefail

EMAIL="chris@maidmentnh.com"
DOMAIN="digitalfuturenh.com"
SERVER_IP="138.197.20.97"

API_KEY="$(ssh root@${SERVER_IP} 'grep ^CLOUDFLARE_API_KEY /opt/nh-whip-count/.env | cut -d= -f2-')"
if [ -z "${API_KEY}" ]; then
  echo "Could not fetch Cloudflare API key from server" >&2
  exit 1
fi

echo "Fetching zone for ${DOMAIN}..."
ZONE_ID="$(curl -s -H "X-Auth-Email: ${EMAIL}" -H "X-Auth-Key: ${API_KEY}" \
  "https://api.cloudflare.com/client/v4/zones?name=${DOMAIN}" | jq -r '.result[0].id // empty')"

if [ -z "${ZONE_ID}" ]; then
  echo "Zone not found in Cloudflare. Add the domain to Cloudflare first." >&2
  exit 1
fi
echo "Zone ID: ${ZONE_ID}"

upsert() {
  local name="$1" content="$2" type="${3:-A}" proxied="${4:-true}"
  local existing
  existing="$(curl -s -H "X-Auth-Email: ${EMAIL}" -H "X-Auth-Key: ${API_KEY}" \
    "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?type=${type}&name=${name}" \
    | jq -r '.result[0].id // empty')"
  local body
  body="$(jq -nc --arg type "${type}" --arg name "${name}" --arg content "${content}" --argjson proxied ${proxied} \
    '{type:$type, name:$name, content:$content, ttl:1, proxied:$proxied}')"
  if [ -n "${existing}" ]; then
    echo "  update ${type} ${name} -> ${content}"
    curl -s -X PUT -H "X-Auth-Email: ${EMAIL}" -H "X-Auth-Key: ${API_KEY}" -H "Content-Type: application/json" \
      "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${existing}" \
      --data "${body}" | jq -r '.success'
  else
    echo "  create ${type} ${name} -> ${content}"
    curl -s -X POST -H "X-Auth-Email: ${EMAIL}" -H "X-Auth-Key: ${API_KEY}" -H "Content-Type: application/json" \
      "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
      --data "${body}" | jq -r '.success'
  fi
}

upsert "${DOMAIN}"        "${SERVER_IP}" A     true
upsert "www.${DOMAIN}"    "${SERVER_IP}" A     true

echo
echo "Done. Verify:"
echo "  dig +short ${DOMAIN}"
echo "  curl -sI https://${DOMAIN}"
