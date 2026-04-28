# Contributing

Thanks for considering a contribution to `kalshi-kit`. The package is small
and the bar for a good PR is correspondingly simple: one focused change,
covered by a test, that leaves the lint and type-check suites clean.

## Setup

Clone the repo and install in editable mode with the development extras:

```bash
git clone https://github.com/AntonioKaram/kalshi-kit.git
cd kalshi-kit
pip install -e ".[dev]"
```

Python 3.12 or newer is required.

## Running checks

Before opening a pull request, run all three commands locally and make sure
they pass:

```bash
pytest
ruff check .
mypy src/
```

CI runs the same commands on Python 3.12 and 3.13. PRs that fail CI will
not be merged until the failures are addressed.

## Pull request guidelines

- **One feature per PR.** Refactors, bug fixes, and new features should be
  separate pull requests so that history stays bisectable. If you find
  yourself wanting to bundle changes, split them.
- **Include a test.** New behavior needs a unit test that exercises it;
  bug fixes need a regression test that fails before the fix and passes
  after. The test suite uses `pytest` with `pytest-asyncio` in auto mode.
- **Conventional-style commits welcome.** `feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:` prefixes make the changelog easy to
  generate but are not enforced.
- **Document non-obvious decisions.** A short comment explaining *why*
  beats a long comment explaining *what*. If your change affects the
  public surface, update the README or the relevant doc under `docs/`.

Issues and design discussions are welcome before code is written for any
non-trivial change.
