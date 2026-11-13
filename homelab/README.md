# homelab

Server side of the stats on my profile card. The R730 (Ubuntu, ZFS, Docker) writes
uptime, running containers and memory usage to a small JSON file every 3 hours.
nginx serves that one file on status.grafkox.de through a Cloudflare Tunnel, but only
with the right bearer token. Everything else gets a 404.

The workflow fetches the file, builds the SVGs and commits them, so visitors of my
profile never send a request to my server. If the server is down, the card says so.

Files:

- `homelab-stats.sh`: collects the numbers (ZFS ARC is not counted as used memory)
- `homelab-stats.service` / `.timer`: runs the script every 3 hours, sandboxed by systemd
- `nginx-status.grafkox.de.conf`: the server block (the token lives in a separate file on the server)
