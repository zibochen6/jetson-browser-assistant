#!/usr/bin/env bash
# Invoked in a real desktop terminal by record_demo.py.
set -uo pipefail
cd "$(dirname "$0")/.."
folder="$1"
export PATH="$HOME/.local/bin:$PATH"
command=(jetson-browser run 'Find one-way flights from Guangzhou to Beijing on 2026-11-20 for 1 adult in economy. Nonstop only, lowest price first. Show up to 3 options and open the fare options for one matching flight.' --keep-open --no-video)
printf '\nJetson Orin NX 16GB · local models · Trip.com\n\n$ '
printf '%q ' "${command[@]}"
printf '\n\n'
"${command[@]}" 2>&1 | tee "$folder/terminal.log"
result=${PIPESTATUS[0]}
printf '%s\n' "$result" > "$folder/exit-code.txt"
printf '\nTask finished with exit code %s. Press Enter to close this window.\n' "$result"
read -r _
