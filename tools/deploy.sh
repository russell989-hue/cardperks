#!/usr/bin/env bash
# Deploy custom_components/cardperks to the Home Assistant box over SSH (no scp on HAOS).
# Usage: tools/deploy.sh [--restart]
#   default: copy files and reload the CardPerks config entry via the Core API. A reload
#            re-runs setup with the Python modules already in memory, so it is only enough
#            for changes to catalog JSON, strings, or other data files.
#   --restart: copy files and restart Home Assistant Core. Required for any change to a
#              .py file (Core never re-imports a custom integration's modules), and on
#              first install.
set -euo pipefail

HOST="${CARDPERKS_HA_HOST:-brianrussell@homeassistant.local}"
KEY="${CARDPERKS_SSH_KEY:-$HOME/.ssh/id_ed25519}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SSH=(ssh -i "$KEY" -o BatchMode=yes "$HOST")

echo ">> syncing custom_components/cardperks -> /config/custom_components/cardperks"
tar -C "$REPO/custom_components" --exclude='__pycache__' --exclude='*.pyc' -cf - cardperks \
  | "${SSH[@]}" 'sudo -n rm -rf /config/custom_components/cardperks.new && sudo -n mkdir -p /config/custom_components && sudo -n tar -C /config/custom_components -xf - && echo synced'

if [[ "${1:-}" == "--restart" ]]; then
  echo ">> restarting Home Assistant Core"
  "${SSH[@]}" 'bash -lc "ha core restart"'
else
  echo ">> reloading cardperks config entries"
  "${SSH[@]}" 'bash -lc "
    ids=\$(curl -s -H \"Authorization: Bearer \$SUPERVISOR_TOKEN\" http://supervisor/core/api/config/config_entries/entry | python3 -c \"import sys,json; print(\\\" \\\".join(e[\\\"entry_id\\\"] for e in json.load(sys.stdin) if e[\\\"domain\\\"]==\\\"cardperks\\\"))\")
    if [ -z \"\$ids\" ]; then echo \"no cardperks entry yet; restart core and add the integration\"; exit 0; fi
    for id in \$ids; do
      curl -s -X POST -H \"Authorization: Bearer \$SUPERVISOR_TOKEN\" http://supervisor/core/api/config/config_entries/entry/\$id/reload; echo
    done"'
fi
