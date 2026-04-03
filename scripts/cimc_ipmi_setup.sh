#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <cimc_host> <user> <password> [channel_security_key]"
  exit 1
fi

CIMC_HOST="$1"
USER="$2"
PASS="$3"
CSK="${4:-0000000000000000000000000000000000000000}"

curl -ksu "${USER}:${PASS}" \
  "https://${CIMC_HOST}/redfish/v1/Managers/CIMC/NetworkProtocol" \
  -XPATCH \
  -H 'Content-Type: application/json' \
  -d "{
    \"IPMI\": {\"ProtocolEnabled\": true},
    \"Oem\": {\"Cisco\": {\"IPMIOverLan\": {
      \"ChannelSecurityKey\": \"${CSK}\",
      \"PrivilegeLevelLimit\": \"admin\"
    }}}
  }"
echo
echo "Requested IPMI over LAN enablement via Redfish."
