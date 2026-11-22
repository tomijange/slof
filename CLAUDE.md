@AGENTS.md

## Claude Code

- [AGENTS.md](AGENTS.md) holds the shared instructions. Put rules for every agent there and keep this file for Claude-specific notes.
- The commit rule in AGENTS.md overrides Claude Code's default attribution: no `Co-Authored-By` trailer, no "Generated with Claude Code" line.
- Activate `.venv` (or call `.venv/bin/python`) before running `make`, `pytest`, `ruff` or `ty`.
