#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
exec uv run uvicorn service.app:app --host 127.0.0.1 --port 5517 --reload
