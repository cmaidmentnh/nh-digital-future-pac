#!/usr/bin/env bash
# Deploy nh-digital-future-pac to the primary server.
#
#   ./scripts/deploy.sh
set -euo pipefail

SERVER="root@138.197.20.97"
APP_DIR="/opt/nh-digital-future-pac"
DOMAIN="digitalfuturenh.com"
ZONE_ID=""  # filled in after first DNS run; or read from the dns script output

echo "==> Pushing latest commit..."
git push origin main

echo "==> Pulling on server..."
ssh "${SERVER}" "
  set -e
  if [ ! -d ${APP_DIR} ]; then
    git clone https://github.com/cmaidmentnh/nh-digital-future-pac.git ${APP_DIR}
  fi
  cd ${APP_DIR} && git pull --ff-only
"

echo "==> Cloudflare cache purge..."
EMAIL=chris@maidmentnh.com
API_KEY="$(ssh ${SERVER} 'grep ^CLOUDFLARE_API_KEY /opt/nh-whip-count/.env | cut -d= -f2-')"
ZONE_ID="$(curl -s -H "X-Auth-Email: ${EMAIL}" -H "X-Auth-Key: ${API_KEY}" \
  "https://api.cloudflare.com/client/v4/zones?name=${DOMAIN}" | jq -r '.result[0].id')"
curl -s -X POST -H "X-Auth-Email: ${EMAIL}" -H "X-Auth-Key: ${API_KEY}" -H "Content-Type: application/json" \
  "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/purge_cache" \
  --data '{"purge_everything":true}' | jq -r '.success'

echo "==> Done."
