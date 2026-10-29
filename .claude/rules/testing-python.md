---
description: Python testing rules - pytest layout, fixtures, parametrisation, mocking seams, fakes for hardware and GUI, import-time side effects, determinism, markers, skips.
paths:
  - "**/test_*.py"
  - "**/*_test.py"
  - "**/tests/**"
  - "**/conftest.py"
  - "pytest.ini"
  - "pyproject.toml"
---

# Python testing rules

These add pytest mechanics to the language-neutral rules in `testing.md`; if they conflict, `testing.md` wins and you raise it. Follow the repo's existing tests first (rule D1): extend its `conftest.py` and fakes instead of starting a second style.

## Layout and style
1. **pytest, plain `assert`.** No `unittest.TestCase` in new tests unless the existing suite is built on it. Run the file you touched first, then the affected set from the command map (`pytest path/to/test_x.py`, `-k <expr>` for one case, `--lf` to re-run only the last failures).
2. One module under test per file: `tests/test_<module>.py`. Name tests for the behaviour (`test_rejects_empty_fragment`), not for the function, and keep one assertion subject per test.
3. **`@pytest.mark.parametrize`** for the same behaviour over several inputs, with readable `ids=`. No loops or `if` inside a test body.
4. Assert on values with the real diff: `assert result == expected`, `pytest.raises(X, match=...)` for errors, `pytest.approx(x, abs=tol)` for floats and signal data with a stated tolerance. `assert x` on a bare boolean hides the cause (`testing.md` rule 12).
5. Test code is typed like production only where it helps; the S3 type-hint rule applies to new public functions, not to every test.

## Fixtures
6. **Fixtures for setup and teardown** (`yield` fixtures, not `try/finally` in tests). Scope narrowly: function by default, `module` or `session` only for something expensive and immutable. Fixtures used by several files live in `conftest.py`; a fixture used once stays beside its test.
7. Built-ins first: `tmp_path` for files, `monkeypatch` for environment variables, attributes and `sys.path`, `capsys`/`caplog` for output and logs. No test writes into the repo, the user's home or a shared directory, and none depends on another test's leftovers or on execution order.
8. A factory fixture (a function the test calls with overrides) beats a pile of near-identical fixtures.

## Mocking and fakes
9. **Mock only the boundary**: hardware, audio and serial devices, network, subprocesses, the clock, randomness. Patch at the seam where the code under test *looks the name up* (`monkeypatch.setattr(module_under_test, "check_output", fake)`), never where it is defined, and never mock the unit under test (`testing.md` rule 3).
10. **Prefer a small hand-written fake over `MagicMock`** for a boundary used in many tests: it keeps the same interface, fails loudly on a wrong call, and lives in `conftest.py`. When you use `mock`, use `create_autospec` or `spec=True` so a misspelled attribute fails, and assert on the effect, not only on `assert_called_with`.
11. **Inject the clock and randomness** (a `now` parameter, a `random.Random(seed)`) rather than patching globals; if patching is unavoidable, patch the module's own reference. Seed every generator (`random`, `numpy`) in the test. Wait for a condition with a bounded poll, never `time.sleep` (`testing.md` rule 5).

## Import-time side effects, GUI and hardware
12. A module that opens a device, reads config or builds a singleton **at import** must be imported only after the environment is isolated: set environment variables (`HOME`, config dirs) and install fakes first, in `conftest.py` or a session fixture that imports lazily. Never let an import touch the developer's real home, config or hardware.
13. Display, audio, GPU and device code is exercised through its fake in unit tests; the real thing is verified by running the app and reported under "Not verified" when it cannot run here (rules B1, B2). Do not start a real window or open a real device in the suite.
14. Keep logic out of widgets and callbacks: put the decision in a plain function the test can call, and test the thin UI glue by hand.

## Markers, skips, flakiness
15. Register every custom marker in `pytest.ini` / `pyproject.toml` and run with `--strict-markers`; mark slow or platform tests (`slow`, `hardware`) so they can be excluded deliberately, never silently.
16. **No `skip`, `skipif`, `xfail` or `pytest.skip()` without a human-approved `# WHY:` and a ticket** (rule B3). A platform-only test is `skipif` with the reason spelled out, not deleted.
17. A flaky test is fixed or quarantined with a ticket in the same PR. `pytest-rerunfailures` or re-running until green is a rule B3 violation.
18. Coverage is a diagnostic: run `--cov` only when the repo already has it, read the uncovered branches of the code you changed, and do not add tests to move a number.

## Bugs
19. A bug fix starts with a test that fails for the right reason (`fix-bug` skill); show the failing run and the passing run.
