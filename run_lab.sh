#!/usr/bin/env bash
# One-command run: all scenarios + pcap capture + fault report.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 src/run_experiment.py
