# Valhacks 2026

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # installs uv, Python 3.12 and deps into .venv
uv run python scripts/unpack.py                         # extract the kits to data/ (password at kick-off)
```

Add packages with `uv add <pkg>` (commit `pyproject.toml` + `uv.lock`). Skills: `.claude/skills/` (Claude Code), `.agents/skills/` (Codex).
