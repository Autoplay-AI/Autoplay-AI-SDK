# Contributing to autoplay-sdk

Thank you for your interest in contributing!

## Dev setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Autoplay-AI/Autoplay-proactive-visual-customer-support.git
cd Autoplay-proactive-visual-customer-support
uv sync
```

To include the optional Redis buffer:

```bash
uv sync --extra redis
```

Install the pre-commit hooks (includes Gitleaks secret scanning):

```bash
pip install pre-commit
pre-commit install
```

## Running tests

```bash
pytest tests/ -v
```

## Making changes

1. Fork the repo and create a branch from `main`.
2. Write tests for any new behaviour.
3. Add a changelog entry in `CHANGELOG.md` under `## Unreleased`.
4. Open a pull request — CI will run tests and Gitleaks automatically.

Need help? Join us on [Discord](https://discord.gg/jCbR2tQA5) — drop a message in `#contributing`.

## Commit style

Use conventional commits where possible:

```
feat: add AsyncRagPipeline.flush()
fix: handle empty session_id in ContextStore.enrich
docs: clarify watermark cutoff semantics
```

## Community standards

- Be respectful and constructive. See `CODE_OF_CONDUCT.md`.
- Report vulnerabilities privately using `SECURITY.md` guidance.
- For support expectations and channels, see `SUPPORT.md`.

## Releasing (maintainers only)

1. Bump the version in `pyproject.toml`.
2. Move `## Unreleased` entries to a new `## vX.Y.Z` section in `CHANGELOG.md`.
3. Commit: `git commit -m "chore: release vX.Y.Z"`.
4. Tag: `git tag vX.Y.Z && git push --tags`.
5. The `publish.yml` workflow publishes to PyPI automatically via Trusted Publisher.
