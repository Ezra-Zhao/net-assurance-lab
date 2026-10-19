#!/usr/bin/env bash
# Start the lab monitoring stack locally (loopback only):
#   exporter  http://127.0.0.1:9108/metrics
#   Prometheus http://127.0.0.1:9090   (needs a prometheus binary)
#   Grafana    http://127.0.0.1:3000   (needs a grafana binary)
#
# Binaries are NOT vendored in this repo. Point the env vars at your
# own installs, e.g.:
#   PROM_BIN=/opt/prometheus/prometheus GRAFANA_BIN=/opt/grafana/bin/grafana \
#       ./monitoring/start_local.sh
# Without them the script starts only what it can and says so.
set -u
cd "$(dirname "$0")/.."
ROOT="$PWD"
DATA="${NAL_MONITORING_DATA:-/tmp/nal-monitoring}"
mkdir -p "$DATA"

echo "+ exporter on 127.0.0.1:9108"
setsid python3 src/prom_exporter.py --port 9108 \
    > "$DATA/exporter.log" 2>&1 &

if [ -n "${PROM_BIN:-}" ] && [ -x "${PROM_BIN}" ]; then
    echo "+ prometheus on 127.0.0.1:9090 (config: monitoring/prometheus.yml)"
    setsid "$PROM_BIN" --config.file=monitoring/prometheus.yml \
        --storage.tsdb.path="$DATA/prom-data" \
        --web.listen-address=127.0.0.1:9090 > "$DATA/prometheus.log" 2>&1 &
else
    echo "skip prometheus: set PROM_BIN to a prometheus binary path"
fi

if [ -n "${GRAFANA_BIN:-}" ] && [ -x "${GRAFANA_BIN}" ]; then
    echo "+ grafana on 127.0.0.1:3000 (provisioning: monitoring/grafana/provisioning)"
    GF_PATHS_DATA="$DATA/grafana-data" \
    GF_PATHS_LOGS="$DATA/grafana-logs" \
    GF_PATHS_PLUGINS="$DATA/grafana-plugins" \
    GF_PATHS_PROVISIONING="$ROOT/monitoring/grafana/provisioning" \
    NETLAB_DASHBOARDS_PATH="$ROOT/monitoring/grafana/dashboards" \
    setsid "$GRAFANA_BIN" server --homepath "$(dirname "$(dirname "$GRAFANA_BIN")")" \
        > "$DATA/grafana.log" 2>&1 &
else
    echo "skip grafana: set GRAFANA_BIN to a grafana binary path"
fi

echo "logs + data under $DATA (processes keep running; kill by port when done)"
