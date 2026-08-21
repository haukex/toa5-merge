
- Python code style preferences:
  - Colons between variable and type names should be on the side of the type name instead of the variable, that is, `foo :int` instead of the default `foo: int`.
  - Prefer single-quoted strings for constant string values, except when the strings contain single quotes themselves (`"don't"`). Prefer double-quoted strings for f-strings.
  - Keep Python lines at or below 150 characters.

- For any `pyright: ignore`, `pylint: disable`, `noqa`, `type: ignore`, `pragma: no cover`, or `pragma: no branch` exclusion comments:
  - First consider if this comment is necessary, or whether you could improve the code instead. However, *do not* use `cast`s or other tricks to "work around" type checker / linter complaints; in those cases just keep the type checker / linter exclusion comment.
  - If you add or modify an exclusion comment, also add an explanatory comment on the preceding line explaining why the exclusion is useful / necessary. Do not add an explanation to a pre-existing exclusion comment that you have not modified; assume its omission was intentional.
  - *Do not* disable type checker / linter directives for an entire file.
  - Never use a general `type: ignore`, always add the specific rule (e.g. `type: ignore[arg-type]`).

- Testing:
  - As a final check before completing work, prefer the default Makefile target `make test`, which runs all checks, lint, and tests. During work, you may also use `make unittest` for tests only (much faster, no linting or coverage), or `make coverage` for tests with coverage (still fast, no linting).
  - For `make` commands, you may need to point to the Python binary explicitly, as in `make test PYTHON3BIN=.venv3.11/bin/python`.
  - If sandbox restrictions prevent running `make test`, request approval.
  - The scripts in `dev` are intended for use when preparing releases; there is no need to run them during normal development.
