#!/usr/bin/env bash
# Writes aggregated homelab numbers for the GitHub profile card.
# Only counts and totals leave the server: no service names, versions or addresses.
set -euo pipefail

OUT_DIR=/srv/homelab-stats
OUT="$OUT_DIR/homelab.json"

uptime_s=$(cut -d. -f1 /proc/uptime)
mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
mem_avail_kb=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)

# The ZFS ARC shows up as "used" but is a cache that shrinks under pressure,
# so it is left out of the memory figure.
arc_b=0
if [[ -r /proc/spl/kstat/zfs/arcstats ]]; then
  arc_b=$(awk '$1 == "size" {print $3}' /proc/spl/kstat/zfs/arcstats)
fi
used_b=$(( (mem_total_kb - mem_avail_kb) * 1024 - arc_b ))
(( used_b < 0 )) && used_b=0

containers=$(docker ps --quiet | wc -l)

tmp=$(mktemp "$OUT_DIR/.homelab.XXXXXX")
printf '{"version":1,"updated":%d,"uptime_seconds":%d,"containers_running":%d,"mem_used_bytes":%d,"mem_total_bytes":%d}\n' \
  "$(date +%s)" "$uptime_s" "$containers" "$used_b" "$(( mem_total_kb * 1024 ))" > "$tmp"
chmod 0644 "$tmp"
mv -f "$tmp" "$OUT"   # atomic: nginx never serves a half-written file
