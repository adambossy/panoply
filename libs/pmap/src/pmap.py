"""A tiny, clean abstraction over ThreadPoolExecutor inspired by `p-map`.

Goals
-----
- Minimal boilerplate: a single `p_map()` function you call with an iterable,
  a mapper, and a `concurrency` cap.
- Hide `ThreadPoolExecutor` mechanics (submission window, shutdown, cancels).
- Preserve input order while running work concurrently.

Non‑goals (for now)
-------------------
- Async-iterable streaming equivalent to `pMapIterable`.
- Abort/timeout control.
- Process pools.

The API mirrors the parts of `p-map` we need:
- `concurrency`: maximum number of mapper calls running at once.
- `stop_on_error` (default True): fail fast on first error; when False, wait for
  all tasks to finish and raise an `ExceptionGroup` of all failures.
- `p_map_skip`: return this sentinel from the mapper to omit a value from the
  output while preserving relative order of the remaining items.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import TypeVar

InT = TypeVar("InT")
OutT = TypeVar("OutT")


class _Skip:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "p_map_skip"


# Sentinel value: mappers can `return p_map_skip` to omit the element.
p_map_skip: object = _Skip()


def p_map(
    iterable: Iterable[InT],
    mapper: Callable[[InT], OutT | object],
    *,
    concurrency: int,
    stop_on_error: bool = True,
) -> list[OutT]:
    """Map ``iterable`` through ``mapper`` with a bounded concurrency limit.

    - The returned list preserves the input order, excluding any items where the
      mapper returned ``p_map_skip``.
    - When ``stop_on_error`` is True (default), the first mapper error is
      propagated immediately and any not-yet-started work is cancelled.
    - When ``stop_on_error`` is False, the function waits for all mappers to
      finish and then raises an ``ExceptionGroup`` if any failed.
    """

    if not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("concurrency must be a positive integer")

    # We avoid pre-materializing the iterable so large inputs don't blow memory.
    it = enumerate(iterable)

    results: dict[int, OutT | object] = {}
    errors: list[Exception] = []
    submitted = 0

    # Track which future maps to which index.
    future_to_idx: dict[Future, int] = {}

    def _submit(pool: ThreadPoolExecutor) -> Future | None:
        nonlocal submitted
        try:
            idx, item = next(it)
        except StopIteration:
            return None
        fut = pool.submit(mapper, item)
        future_to_idx[fut] = idx
        submitted += 1
        return fut

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            # Prime the window
            active: set[Future] = set()
            for _ in range(concurrency):
                fut = _submit(pool)
                if fut is None:
                    break
                active.add(fut)

            # Drive completion/queueing until all work is done.
            while active:
                done, active = wait(active, return_when=FIRST_COMPLETED)

                # For each finished future, record and top up the window.
                for fut in done:
                    idx = future_to_idx.pop(fut)
                    try:
                        val = fut.result()
                        results[idx] = val
                    except Exception as e:  # noqa: BLE001
                        if stop_on_error:
                            # Best-effort: cancel anything not started yet and
                            # ask the pool to stop accepting new work.
                            try:
                                pool.shutdown(wait=False, cancel_futures=True)
                            finally:
                                raise
                        errors.append(e)

                # Top up: for each completion, try to submit one more task.
                for _ in range(len(done)):
                    fut = _submit(pool)
                    if fut is None:
                        break
                    active.add(fut)

    except Exception:
        # Let caller handle/log; no extra wrapping here to keep tracebacks clean.
        raise

    if errors:
        # Python 3.11+: group multiple errors when not failing fast.
        raise ExceptionGroup("p_map: one or more mapper calls failed", errors)

    # Stitch output in input order, skipping sentinels.
    out: list[OutT] = []
    for i in range(submitted):
        val = results.get(i, p_map_skip)
        if val is p_map_skip:
            continue
        out.append(val)  # type: ignore[arg-type]
    return out


__all__ = ["p_map", "p_map_skip"]
