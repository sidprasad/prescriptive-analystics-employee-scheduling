# Search Strategy Benchmark: Custom vs Built-in vs Hybrid

## Strategies

| Strategy | Shift variable selection | Shift value selection | Duration handling | Python overhead |
|----------|------------------------|----------------------|-------------------|----------------|
| **custom** | Fail-first across shift+duration pool (Python) | Weighted-random (night deprioritised) | Max-first (Python) | High — every assignment goes through Python |
| **builtin** | `CHOOSE_MIN_SIZE_LOWEST_MIN` (C++) | `ASSIGN_RANDOM_VALUE` (uniform) | `ASSIGN_MAX_VALUE` (C++) | None — all C++ |
| **hybrid** | Fail-first over shifts only (Python) | Weighted-random (night deprioritised) | `ASSIGN_MAX_VALUE` (C++) | Medium — only shift assignments go through Python |

## Results

All runs use a 60s time limit and Luby restarts (base 100).

| Input | Strategy | Time (s) | Failures | Solved | Valid |
|-------|----------|----------|----------|--------|-------|
| 7_14.sched | custom | 0.01 | 2 | yes | yes |
| 7_14.sched | builtin | 0.00 | 2 | yes | yes |
| 7_14.sched | hybrid | 0.05 | 1,802 | yes | yes |
| 7_17.sched | custom | 0.06 | 608 | yes | yes |
| 7_17.sched | builtin | 0.00 | 1 | yes | yes |
| 7_17.sched | hybrid | 0.01 | 35 | yes | yes |
| 7_20.sched | custom | 0.01 | 0 | yes | yes |
| 7_20.sched | builtin | 0.00 | 0 | yes | yes |
| 7_20.sched | hybrid | 0.01 | 0 | yes | yes |
| 14_14.sched | custom | 0.35 | 1,808 | yes | yes |
| 14_14.sched | builtin | 0.02 | 3,600 | yes | yes |
| 14_14.sched | hybrid | 1.41 | 27,806 | yes | yes |
| 14_15.sched | custom | 60.0 | 521,720 | **no** | — |
| 14_15.sched | builtin | 4.62 | 1,710,802 | yes | yes |
| 14_15.sched | hybrid | 60.0 | 1,377,375 | **no** | — |
| 14_17.sched | custom | 60.0 | 408,201 | **no** | — |
| 14_17.sched | builtin | 60.0 | 12,215,601 | **no** | — |
| 14_17.sched | hybrid | 60.0 | 1,093,572 | **no** | — |
| 14_18.sched | custom | 0.19 | 501 | yes | yes |
| 14_18.sched | builtin | 0.02 | 1,708 | yes | yes |
| 14_18.sched | hybrid | 0.04 | 203 | yes | yes |

## Throughput comparison (failures per second at 60s timeout)

| Strategy | 14_15 fails/sec | 14_17 fails/sec |
|----------|----------------|----------------|
| custom | ~8,700 | ~6,800 |
| builtin | ~380,000 | ~203,000 |
| hybrid | ~23,000 | ~18,200 |

Hybrid achieves **~2.5x** the throughput of custom while keeping weighted-random shift value selection.

## Analysis

### 14_18.sched — hybrid wins
Hybrid: 203 failures, 0.04s. Custom: 501 failures, 0.19s. Builtin: 1,708 failures, 0.02s.
Hybrid has the best failure count AND good speed. Weighted-random shift selection does its job, and offloading durations to C++ keeps wall-clock low.

### 14_14.sched — custom wins on failures, builtin wins on time
Custom: 1,808 failures, 0.35s. Builtin: 3,600 failures, 0.02s. Hybrid: 27,806 failures, 1.41s.
On this instance, interleaving shifts+durations (custom) genuinely helps reduce failures. But builtin is so fast it doesn't matter. Hybrid underperforms here — the two-phase separation hurts more than the speed gain helps.

### 14_15.sched — builtin is the only one that solves it
Only builtin finds a solution (4.62s, 1.7M failures). Custom and hybrid both time out. Even though hybrid reaches 1.37M failures (vs custom's 521K), it's not enough. Pure C++ throughput is decisive here.

### 14_17.sched — nothing works
All three time out. Hybrid explores 1.09M failures, builtin 12.2M, custom 408K. None find a solution within 60s.

## Key Takeaway

- **Hybrid sits between custom and builtin**: ~2.5x faster than custom, keeps weighted-random shift selection, but still ~15x slower than pure C++ builtin.
- On easy instances (7_*), all strategies work — the choice doesn't matter.
- On hard instances (14_15), **raw throughput dominates** — builtin wins by brute force.
- On medium instances (14_14, 14_18), **smarter decisions matter** — custom/hybrid need fewer failures.
- The ideal approach would implement weighted-random value selection in C++, combining smart decisions with high throughput.
