---
description: Python code rules - type hints, error handling, logging, resources, mutable state, configuration and secrets.
paths:
  - "**/*.py"
---

# Python code rules

Read the neighbouring modules first and follow their pattern (rule D1); these rules are the floor, not a replacement for the repo's conventions (rule D2).

1. **Type hints on every public function and method** in new code (parameters and return). Use the standard `typing` forms the pinned Python version supports: on 3.9 write `Optional[X]` and `List[X]` or `from __future__ import annotations`, not `X | None` at runtime.
2. **Errors are never swallowed.** No bare `except:`, no `except Exception: pass`, no silent `return None` standing in for a failure. Catch the narrowest exception you can handle, log it with context, and re-raise or return an explicit error value (rule D5).
3. **`logging`, not `print`**, in application code. One logger per module (`logging.getLogger(__name__)`); never log secrets, tokens or personal data (rule D8).
4. **Resources use context managers**: files, sockets, locks, audio/serial/hardware handles, subprocesses. A resource opened without `with` needs a `try/finally` that closes it.
5. **No mutable default arguments** (`def f(x=[])`). No module-level mutable state that tests cannot reset; a singleton is allowed only when the repo already uses one deliberately.
6. **Concurrency is explicit.** Say in a comment which thread or process owns a piece of state. Shared state between threads needs a lock or a queue; between processes, `multiprocessing` primitives, not module globals. Never block the thread that runs a UI or an event loop with I/O or `sleep`.
7. **`pathlib.Path`** for new path handling; no hand-built `"dir/" + name` strings and no hard-coded absolute paths.
8. **Configuration and secrets come from the environment or the repo's config module**, never from literals. A new setting is added in the place the repo already keeps its settings.
9. Imports at the top, grouped standard library / third party / local, no wildcard imports, no import-time side effects beyond what the module already does.
10. Hardware, network and filesystem access sits behind a small boundary the tests can fake; business logic receives it, it does not reach for it.
11. Comments explain *why*, never *what*; no commented-out code; no `TODO` without a ticket (rule D6).
