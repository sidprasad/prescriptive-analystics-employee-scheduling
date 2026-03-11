"""Custom decision builders for the employee scheduling CP model."""
from __future__ import annotations

import random

from ortools.constraint_solver import pywrapcp

NIGHT_SHIFT = 1  # weak assumption: night shift is always shift 1


class InterleavedSelector(pywrapcp.PyDecisionBuilder):
    """
    Interleave shift and duration variables so constraint propagation between the two kicks in
    immediately — no more assigning *all* shifts before touching durations.

    Variable selection (both types):
      CHOOSE_MIN_SIZE_LOWEST_MIN — fail-first across the combined pool.
      Naturally handles training-phase days (AllDifferent), high-demand days
      (minDemandDayShift), and late-week budget pressure (minWeeklyWork /
      maxWeeklyWork) without any explicit priority rules.

    Value selection:
      • Shift vars  → weighted-random with night deprioritised (night is
        doubly capped by maxConsecutiveNightShift and maxTotalNightShift, so
        conserving it reduces backtracking). Randomness lets Luby restarts
        diversify the search tree.
      • Duration vars → ASSIGN_MAX_VALUE — maximise hours first to
        satisfy minDailyOperation / minWeeklyWork with fewer backtracks.
    """

    def __init__(self, shift_vars, duration_vars, num_shifts, max_daily_work):
        super().__init__()
        self._shift_set = set(id(v) for v in shift_vars)
        self._all_vars      = list(shift_vars) + list(duration_vars)
        self._num_shifts    = num_shifts
        self._max_daily_work = max_daily_work

    def Next(self, solver_):
        # --- Variable selection: fail-first across combined shift+duration pool ---
        most_constrained_var = None
        fewest_choices    = self._num_shifts + 1
        lowest_domain_min = self._max_daily_work + 1
        for v in self._all_vars:
            if v.Bound():
                continue
            domain_size = v.Size()
            domain_min  = v.Min()
            if domain_size < fewest_choices or (domain_size == fewest_choices and domain_min < lowest_domain_min):
                most_constrained_var = v
                fewest_choices    = domain_size
                lowest_domain_min = domain_min

        if most_constrained_var is None:
            return None

        # --- Value selection ---
        if id(most_constrained_var) in self._shift_set:
            shift_weights = [1, 2, 3, 3]   # off, night, day, evening
            domain  = [s for s in range(self._num_shifts) if most_constrained_var.Contains(s)]
            weights = [shift_weights[s] for s in domain]
            chosen  = random.choices(domain, weights=weights, k=1)[0]
        else:
            chosen = most_constrained_var.Max()

        return solver_.AssignVariableValue(most_constrained_var, chosen)


class ShiftOnlySelector(pywrapcp.PyDecisionBuilder):
    """
    Custom decision builder for SHIFT variables only.

    Same weighted-random value selection as InterleavedSelector, but only
    scans shift variables — duration variables are handled by a separate
    C++ builtin Phase. This cuts the number of Python Next() calls roughly
    in half, since duration assignments stay entirely in C++.

    Used by the 'hybrid' strategy.
    """

    def __init__(self, shift_vars, num_shifts):
        super().__init__()
        self._shift_vars = list(shift_vars)
        self._num_shifts = num_shifts

    def Next(self, solver_):
        # Fail-first scan over shift variables only (smaller list → faster).
        most_constrained_var = None
        fewest_choices    = self._num_shifts + 1
        lowest_domain_min = self._num_shifts + 1
        for v in self._shift_vars:
            if v.Bound():
                continue
            domain_size = v.Size()
            domain_min  = v.Min()
            if domain_size < fewest_choices or (domain_size == fewest_choices and domain_min < lowest_domain_min):
                most_constrained_var = v
                fewest_choices    = domain_size
                lowest_domain_min = domain_min

        if most_constrained_var is None:
            return None  # all shift vars assigned — hand off to duration phase

        # Weighted-random: deprioritise night (scarce budget), prefer day/evening.
        shift_weights = [1, 2, 3, 3]   # off, night, day, evening
        domain  = [s for s in range(self._num_shifts) if most_constrained_var.Contains(s)]
        weights = [shift_weights[s] for s in domain]
        chosen  = random.choices(domain, weights=weights, k=1)[0]

        return solver_.AssignVariableValue(most_constrained_var, chosen)


def build_search(solver, shift_vars, duration_vars, num_shifts, max_daily_work,
                 strategy="custom"):
    """
    Build a DecisionBuilder for the employee scheduling model.

    strategy:
      "custom"   — InterleavedSelector: single interleaved pool of shift + duration
                   vars, fail-first variable selection, weighted-random shift values,
                   max-first duration values. All in Python — smart but slow.

      "builtin"  — Pure C++ two-phase: solver.Phase with CHOOSE_MIN_SIZE_LOWEST_MIN
                   + ASSIGN_RANDOM_VALUE for shifts, then ASSIGN_MAX_VALUE for
                   durations. Fast but no domain-aware value weighting.

      "hybrid"   — Best of both: Python ShiftOnlySelector (weighted-random, fail-first)
                   for shifts, then C++ solver.Phase for durations. Cuts Python Next()
                   calls roughly in half vs custom while keeping the smart shift
                   value selection.

    Returns (db, refs) where refs must be kept alive to prevent GC of
    any Python DecisionBuilder (OR-Tools C++ does not prevent it).
    """
    if strategy == "builtin":
        phase_shifts = solver.Phase(
            shift_vars,
            solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
            solver.ASSIGN_RANDOM_VALUE,
        )
        phase_durations = solver.Phase(
            duration_vars,
            solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
            solver.ASSIGN_MAX_VALUE,
        )
        db = solver.Compose([phase_shifts, phase_durations])
        return db, [phase_shifts, phase_durations]

    elif strategy == "hybrid":
        # Python for shifts (weighted-random), C++ for durations (max-first).
        phase_shifts = ShiftOnlySelector(shift_vars, num_shifts)
        phase_durations = solver.Phase(
            duration_vars,
            solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
            solver.ASSIGN_MAX_VALUE,
        )
        db = solver.Compose([phase_shifts, phase_durations])
        return db, [phase_shifts, phase_durations]

    else:  # "custom"
        db = InterleavedSelector(shift_vars, duration_vars, num_shifts, max_daily_work)
        return db, [db]
