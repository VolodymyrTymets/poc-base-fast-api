---
description: Testing rules — levels, mocking boundaries, determinism, flaky tests, coverage. Language- and framework-neutral.
paths:
  - "**/*test*"
  - "**/*spec*"
  - "**/__tests__/**"
  - "**/tests/**"
  - "e2e/**"
---

# Testing rules

1. **Test at the level where it can break.** Pure logic in unit tests; the contract at the boundary (HTTP, queue, CLI) in integration tests; user journeys end to end. If you cannot name what would break, do not write the test.
2. **One level per behaviour.** Do not re-test the same rule at three levels; that triples the maintenance and proves nothing extra.
3. **Never mock what you own and can run cheaply.** Mock the network edge, the clock, randomness and third-party services. Do not mock your own data layer in an integration test, and never mock the thing under test.
4. **Every bug fix starts with a failing test** that reproduces it. No repro, no fix (see the `fix-bug` skill).
5. **Deterministic or it does not count**: fixed clock, seeded data, no reliance on test order, no shared mutable state, no sleeps — wait for a condition.
6. **A flaky test is fixed or quarantined with a ticket in the same PR.** Re-running until green is a rule B3 violation.
7. **Coverage is a diagnostic, not a target.** Business rules and shared code need tests; padding does not count.
8. Test names state the behaviour — `rejects an order when the cart is empty`, not `works`.
9. One assertion subject per test, arrange/act/assert visually separated. If a test needs a comment to explain what it asserts, split it.
10. Factories or fixtures for anything reused; each test creates what it needs and cleans up after itself.
11. Assert on observable behaviour and public contracts, not on internal structure — a test that breaks on every refactor is a cost, not a safety net.
12. The failure message must identify the cause without a debugger. Assert on values, not on booleans.

Framework-specific patterns (runner flags, component-testing helpers, device automation) live in the
stack pack for this repo's stack, not here.
