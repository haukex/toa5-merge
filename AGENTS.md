
- Python code style preferences:
  - Colons between variable and type names should be on the side of the type name instead of the variable, that is, `foo :int` instead of the default `foo: int`.
  - Prefer single-quoted strings for constant string values, except when the strings contain single quotes themselves (`"don't"`). Prefer double-quoted strings for f-strings.
  - Keep Python lines at or below 150 characters.

- For any `pyright: ignore`, `pylint: disable`, `noqa`, `type: ignore`, `pragma: no cover`, or `pragma: no branch` exclusion comments:
  - First consider if this comment is necessary, or whether you could improve the code instead. However, *do not* use `cast`s or other tricks to "work around" type checker / linter complaints; in those cases just keep the type checker / linter exclusion comment.
  - If you add or modify an exclusion comment, also add an explanatory comment on the preceding line explaining why the exclusion is useful / necessary. Do not add an explanation to a pre-existing exclusion comment that you have not modified; assume its omission was intentional.
  - *Do not* disable type checker / linter directives for an entire file.
  - Never use a general `type: ignore`, always add the specific rule (e.g. `type: ignore[arg-type]`).

- Prefer inlining variables (including constants) that are only used once, and prefer inlining functions that consist of only one statement or that are called in only one place.
- Instead of dataclasses or named tuples that only have two or three members and that are only used in one place, prefer tuples with clear types (implicit types are fine).

- Testing:
  - Prefer the default Makefile target `make test`, which runs all checks, lint, and tests. During work, use `make unittest` for tests only (much faster, no linting or coverage), or `make coverage` for tests with coverage (still fast, no linting).
  - For `make` commands, you may need to point to the Python binary explicitly, as in `make test PYTHON3BIN=.venv3.11/bin/python`. If there isn't a `.venv*` in the current project, check `~/.venvs/project-name/.venv*`, and if that exists, pick the Python with the lowest version.
  - The scripts in `dev` are intended for use when preparing releases; there is no need to run them during normal development.

- On native Windows (not WSL), always prefer the Git Bash installed at `%LOCALAPPDATA%\Programs\Git` over a global installation.
