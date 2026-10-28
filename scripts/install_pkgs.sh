#!/bin/bash
# SessionStart hook: prepare a fresh remote (cloud) Claude Code session.
# Local sessions already have .venv and the unpacked archive, so it exits.
if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then exit 0; fi
cd "$CLAUDE_PROJECT_DIR" || exit 1
set -e
command -v uv >/dev/null || pip install --quiet uv
uv sync
[ -f data/emails/emails.jsonl ] || uv run python data/download.py
exit 0
