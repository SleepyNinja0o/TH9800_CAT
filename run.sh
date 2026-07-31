#!/usr/bin/env bash
cd "$(dirname "${BASH_SOURCE[0]}")"
exec "$(dirname "${BASH_SOURCE[0]}")/venv/bin/python" TH9800_CAT.py "$@"
