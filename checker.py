#!/usr/bin/env python3
"""
Solution checker for Employee Scheduling instances.

Usage:
    python3 checker.py <instance.sched> <solution_string>
    python3 checker.py <instance.sched> --json <results.json>

The solution string is the flat space-separated begin/end pairs:
    "8 16 -1 -1 0 8 ..."
    (numEmployees * numDays * 2 integers)

Exit code 0 = all constraints satisfied, 1 = violations found.
"""

import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from cpinstance import CPInstance


def get_shift(begin, end, hours_per_shift):
    """Return shift label (0=off, 1=night, 2=day, 3=evening) or -1 if invalid."""
    if begin == -1 and end == -1:
        return 0  # off
    for s in range(1, 4):
        window_start = (s - 1) * hours_per_shift
        window_end = window_start + hours_per_shift
        if window_start <= begin < window_end and window_start < end <= window_end:
            return s
    return -1  # invalid


def check(inst: CPInstance, sched):
    """
    Validate sched[e][d] = (begin, end) against all constraints.
    Returns list of error strings (empty = valid).
    """
    E = inst.numEmployees
    D = inst.numDays
    S = inst.numShifts
    hours_per_shift = inst.numIntervalsInDay // (S - 1)
    errors = []

    # ── Shape check ──────────────────────────────────────────────────────
    if len(sched) != E:
        errors.append(f"Expected {E} employees, got {len(sched)}")
        return errors
    for e in range(E):
        if len(sched[e]) != D:
            errors.append(f"Employee {e}: expected {D} days, got {len(sched[e])}")
            return errors

    # Derive shift labels
    shift_of = [[get_shift(sched[e][d][0], sched[e][d][1], hours_per_shift) for d in range(D)] for e in range(E)]
    hours_of = [[0 if sched[e][d][0] == -1 else sched[e][d][1] - sched[e][d][0] for d in range(D)] for e in range(E)]

    # ── 1. Valid shift assignments ────────────────────────────────────────
    for e in range(E):
        for d in range(D):
            b, en = sched[e][d]
            s = shift_of[e][d]
            if s == -1:
                errors.append(f"E{e} D{d}: invalid time window [{b},{en}) — doesn't fit any shift")
            elif s > 0:
                hrs = en - b
                if hrs < inst.minConsecutiveWork:
                    errors.append(f"E{e} D{d}: {hrs}h worked < minConsecutiveWork={inst.minConsecutiveWork}")
                if hrs > inst.maxDailyWork:
                    errors.append(f"E{e} D{d}: {hrs}h worked > maxDailyWork={inst.maxDailyWork}")
                if b >= en:
                    errors.append(f"E{e} D{d}: begin={b} >= end={en}")

    # ── 2. Training phase (first numShifts days): AllDifferent shifts ────
    for e in range(E):
        training = [shift_of[e][d] for d in range(S)]
        if sorted(training) != list(range(S)):
            errors.append(f"E{e} training (days 0..{S-1}): shifts={training}, expected each of {list(range(S))} exactly once")

    # ── 3. Min demand per shift per day ──────────────────────────────────
    for d in range(D):
        counts = [0] * S
        for e in range(E):
            s = shift_of[e][d]
            if 0 <= s < S:
                counts[s] += 1
        for s in range(S):
            req = inst.minDemandDayShift[d][s]
            if counts[s] < req:
                errors.append(f"D{d} shift {s}: {counts[s]} employees < demand={req}")

    # ── 4. Min daily operation (total hours across all employees) ────────
    for d in range(D):
        total = sum(hours_of[e][d] for e in range(E))
        if total < inst.minDailyOperation:
            errors.append(f"D{d}: total hours={total} < minDailyOperation={inst.minDailyOperation}")

    # ── 5. Weekly work hour bounds ───────────────────────────────────────
    DAYS_PER_WEEK = 7
    for e in range(E):
        for w in range(D // DAYS_PER_WEEK):
            wh = sum(hours_of[e][d] for d in range(w * DAYS_PER_WEEK, (w + 1) * DAYS_PER_WEEK))
            if wh < inst.minWeeklyWork:
                errors.append(f"E{e} week {w}: {wh}h < minWeeklyWork={inst.minWeeklyWork}")
            if wh > inst.maxWeeklyWork:
                errors.append(f"E{e} week {w}: {wh}h > maxWeeklyWork={inst.maxWeeklyWork}")

    # ── 6. Max consecutive night shifts ──────────────────────────────────
    NIGHT = 1
    for e in range(E):
        window = inst.maxConsecutiveNightShift + 1
        for d in range(D - inst.maxConsecutiveNightShift):
            n = sum(1 for k in range(window) if shift_of[e][d + k] == NIGHT)
            if n > inst.maxConsecutiveNightShift:
                errors.append(f"E{e} D{d}..{d+window-1}: {n} night shifts > maxConsecutiveNightShift={inst.maxConsecutiveNightShift}")

    # ── 7. Max total night shifts ────────────────────────────────────────
    for e in range(E):
        total_n = sum(1 for d in range(D) if shift_of[e][d] == NIGHT)
        if total_n > inst.maxTotalNightShift:
            errors.append(f"E{e}: {total_n} total night shifts > maxTotalNightShift={inst.maxTotalNightShift}")

    return errors


def parse_solution_string(sol_str, num_employees, num_days):
    """Parse flat space-separated solution string into sched[e][d] = (begin, end)."""
    vals = list(map(int, sol_str.split()))
    expected = num_employees * num_days * 2
    if len(vals) != expected:
        raise ValueError(f"Solution has {len(vals)} values, expected {expected} ({num_employees} employees x {num_days} days x 2)")
    sched = []
    idx = 0
    for e in range(num_employees):
        row = []
        for d in range(num_days):
            row.append((vals[idx], vals[idx + 1]))
            idx += 2
        sched.append(row)
    return sched


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)

    inst_file = sys.argv[1]
    inst = CPInstance(inst_file)

    if sys.argv[2] == "--json":
        # Read from JSON results file
        json_file = sys.argv[3]
        target = Path(inst_file).name
        with open(json_file) as f:
            for line in f:
                d = json.loads(line)
                if d["Instance"] == target and "Solution" in d and d["Solution"]:
                    sol_str = d["Solution"]
                    break
            else:
                print(f"No solution found for {target} in {json_file}")
                sys.exit(1)
    else:
        sol_str = sys.argv[2]

    sched = parse_solution_string(sol_str, inst.numEmployees, inst.numDays)
    errors = check(inst, sched)

    if errors:
        print(f"FAILED — {len(errors)} violation(s):")
        for err in errors:
            print(f"  ✗ {err}")
        sys.exit(1)
    else:
        print(f"PASSED — all constraints satisfied for {Path(inst_file).name}")
        print(f"  {inst.numEmployees} employees, {inst.numDays} days, {inst.numShifts} shifts")
        sys.exit(0)


if __name__ == "__main__":
    main()
