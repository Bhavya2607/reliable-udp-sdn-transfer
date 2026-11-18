#!/usr/bin/env bash
set -euo pipefail
python3 -m py_compile protocol.py client.py server.py controller.py topology.py experiments/benchmark.py
python3 -m unittest discover -s tests -v
