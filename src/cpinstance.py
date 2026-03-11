from __future__ import annotations

import json
import sys
from typing import Optional, List, Tuple

import numpy as np
from ortools.constraint_solver import pywrapcp

from search import build_search



class CPInstance:
    # BUSINESS parameters
    numWeeks: int ## SP: Is it days + weeks or either?
    numDays: int
    numEmployees: int
    numShifts: int  ## The off shift is denoted by 0 while work shifts, night, day, and evening are denoted by 1, 2, and 3 respectively. 
    numIntervalsInDay: int 
    minDemandDayShift: list[list[int]]  ## e.g. minDemandDayShift[d][s] = 2 means that on day d at least 2 employees should be working day shift s.
    minDailyOperation: int  ## a minimum demand needs to be met to ensure the daily operation for every day when considering all employees and shifts.
    


    ## ADDED BY SP
    # Treat the first numShifts days as the training phase. 
    # Each employee must see each of the shift labels exactly once across those days, including the off shift.

    # EMPLOYEE parameters
    minConsecutiveWork: int
    maxDailyWork: int
    minWeeklyWork: int
    maxWeeklyWork: int
    maxConsecutiveNightShift: int
    maxTotalNightShift: int

    # Solver
    solver: pywrapcp.Solver

    def __init__(self, filename: str):
        self.load_from_file(filename)
        self.solver = None

    def load_from_file(self, f: str):
        """
        Reads in a file and populates the instance parameters.
        """
        params = {} 
        if not f:
            print("No file provided")
            return
        with open(f, "r") as fl:
            lines = fl.readlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("Business_"):
                    key, value = line.split(":")
                    if key != "Business_minDemandDayShift":
                        params[key] = int(value)
                    else:
                        params[key] = [int(x) for x in value.split()]
                elif line.startswith("Employee_"):
                    key, value = line.split(":")
                    params[key] = int(value)
                
        self.numWeeks = params.get("Business_numWeeks")
        self.numDays = params.get("Business_numDays")
        self.numEmployees = params.get("Business_numEmployees")
        self.numShifts = params.get("Business_numShifts")
        self.numIntervalsInDay = params.get("Business_numIntervalsInDay")
        
        raw = params.get("Business_minDemandDayShift", [])
        self.minDemandDayShift = []
        if raw:
            for i in range(0, self.numDays * self.numShifts, self.numShifts):
                self.minDemandDayShift.append(raw[i : i + self.numShifts])
                
        self.minDailyOperation = params.get("Business_minDailyOperation")
        self.minConsecutiveWork = params.get("Employee_minConsecutiveWork")
        self.maxDailyWork = params.get("Employee_maxDailyWork")
        self.minWeeklyWork = params.get("Employee_minWeeklyWork")
        self.maxWeeklyWork = params.get("Employee_maxWeeklyWork")
        self.maxConsecutiveNightShift = params.get("Employee_maxConsecutiveNigthShift")
        self.maxTotalNightShift = params.get("Employee_maxTotalNigthShift")


    def solve(
        self,
        time_limit_seconds: Optional[float] = None,
        strategy: str = "interleaved",
    ):
        """
        Two primary decision-variable matrices:
          shiftOfEmployeeDay[e][d]    -- shift label in {0 .. numShifts-1}
          durationOfEmployeeDay[e][d] -- hours worked in {0 .. maxDailyWork}

        Invariant (correspondence):
          shiftOfEmployeeDay[e][d] == OFF_SHIFT  ↔  durationOfEmployeeDay[e][d] == 0

        Shift legend (per handout):
          0 = off, 1 = night, 2 = day, 3 = evening
        """
        OFF_SHIFT   = 0
        NIGHT_SHIFT = 1
        DAYS_PER_WEEK = 7

        self.solver = pywrapcp.Solver("EmployeeScheduling")
        solver = self.solver

        shifts    = list(range(self.numShifts))
        days      = list(range(self.numDays))
        employees = list(range(self.numEmployees))

        # ------------------------------------------------------------------ #
        # Decision variables                                                   #
        # ------------------------------------------------------------------ #

        # shiftOfEmployeeDay[e][d]: which shift employee e works on day d.
        shiftOfEmployeeDay = [
            [solver.IntVar(0, self.numShifts - 1, f"shift_{e}_{d}") for d in days]
            for e in employees
        ]

        # durationOfEmployeeDay[e][d]: how many hours employee e works on day d.
        # Domain is [0, maxDailyWork]; the correspondence constraint below further
        # restricts it to 0 when off and [minConsecutiveWork, maxDailyWork] when working.
        durationOfEmployeeDay = [
            [solver.IntVar(0, self.maxDailyWork, f"dur_{e}_{d}") for d in days]
            for e in employees
        ]

        # Correspondence: shiftOfEmployeeDay[e][d] == off  ↔  duration == 0  #
        for e in employees:
            for d in days:
                is_off = solver.IsEqualCstVar(shiftOfEmployeeDay[e][d], OFF_SHIFT)
                solver.Add(durationOfEmployeeDay[e][d] <= self.maxDailyWork * (1 - is_off))
                solver.Add(durationOfEmployeeDay[e][d] >= self.minConsecutiveWork * (1 - is_off))

        # ------------------------------------------------------------------ #
        # Business constraints                                                 #
        # ------------------------------------------------------------------ #

        # Min employees per shift per day via Global Cardinality (Distribute).
        # For each day d, the column of shift variables must satisfy:
        #   |{e : shiftOfEmployeeDay[e][d] == s}| >= minDemandDayShift[d][s]  for all s.
        for d in days:
            col       = [shiftOfEmployeeDay[e][d] for e in employees]
            card_mins = [self.minDemandDayShift[d][s] for s in shifts]
            card_maxs = [self.numEmployees] * self.numShifts
            solver.Add(solver.Distribute(col, card_mins, card_maxs))

        # Minimum total hours worked across all employees each day.
        for d in days:
            solver.Add(
                solver.Sum([durationOfEmployeeDay[e][d] for e in employees]) >= self.minDailyOperation
            )

        # ------------------------------------------------------------------ #
        # Training phase: each employee sees every shift label exactly once   #
        # across the first numShifts days (includes the off shift).           #
        # ------------------------------------------------------------------ #
        for e in employees:
            training_vars = [shiftOfEmployeeDay[e][d] for d in range(self.numShifts)]
            solver.Add(solver.AllDifferent(training_vars))

        # ------------------------------------------------------------------ #
        # Employee constraints                                                 #
        # ------------------------------------------------------------------ #

        # Weekly work-hour bounds for each complete 7-day week.
        # Partial trailing weeks (numDays % 7 != 0) are ignored.
        num_full_weeks = self.numDays // DAYS_PER_WEEK
        for e in employees:
            for w in range(num_full_weeks):
                week_days    = list(range(w * DAYS_PER_WEEK, (w + 1) * DAYS_PER_WEEK))
                weekly_hours = solver.Sum([durationOfEmployeeDay[e][d] for d in week_days])
                solver.Add(weekly_hours >= self.minWeeklyWork)
                solver.Add(weekly_hours <= self.maxWeeklyWork)

        # Consecutive night-shift limit.
        # A night shift on day d implies no night shifts on days d+1 .. d+maxConsecutiveNightShift.
        # Equivalently: in any window of (maxConsecutiveNightShift + 1) consecutive days,
        # at most maxConsecutiveNightShift can be night shifts.
        for e in employees:
            for d in range(self.numDays - self.maxConsecutiveNightShift):
                window = [
                    solver.IsEqualCstVar(shiftOfEmployeeDay[e][d + k], NIGHT_SHIFT)
                    for k in range(self.maxConsecutiveNightShift + 1)
                ]
                solver.Add(solver.Sum(window) <= self.maxConsecutiveNightShift)

        # Total night-shift cap per employee.
        for e in employees:
            is_night = [solver.IsEqualCstVar(shiftOfEmployeeDay[e][d], NIGHT_SHIFT) for d in days]
            solver.Add(solver.Sum(is_night) <= self.maxTotalNightShift)






        shift_vars    = [shiftOfEmployeeDay[e][d]    for e in employees for d in days]
        duration_vars = [durationOfEmployeeDay[e][d] for e in employees for d in days]


        # Using custom heuristic from 'search' module.
        db, _search_refs = build_search(solver, shift_vars, duration_vars, self.numShifts, self.maxDailyWork, strategy=strategy)

        # Luby restarts with a base unit of 100 failures.
        # Because the shift selector uses weighted-random value selection,
        # each restart explores a genuinely different region of the tree.
        # Earlier, we had a deterministic search strategy, which means 
        # that these restarts were sort of useless.
        restart = solver.LubyRestart(100)

        limits = [restart]
        if time_limit_seconds is not None:
            limits.append(solver.TimeLimit(int(time_limit_seconds * 1000)))
        solver.NewSearch(db, limits)

        if solver.NextSolution():
            hours_per_slot = self.numIntervalsInDay // (self.numShifts - 1)
            shift_start = {0: -1}  # off: sentinel, consistent with what prettyPrint expects
            for s in range(1, self.numShifts):
                shift_start[s] = (s - 1) * hours_per_slot

            schedule = [
                [
                    (
                        lambda s, dur: (-1, -1) if s == OFF_SHIFT
                        else (shift_start[s], shift_start[s] + dur)
                    )(shiftOfEmployeeDay[e][d].Value(), durationOfEmployeeDay[e][d].Value())
                    for d in days
                ]
                for e in employees
            ]
            solver.EndSearch()
            return True, solver.Failures(), schedule
        else:
            solver.EndSearch()
            return False, solver.Failures(), []


    def check_solution(self, sched: list) -> list[str]:
        """
        Verifies sched against every model constraint and returns a list of
        violation strings.  An empty list means the solution is valid.

        sched[e][d] = (begin, end) using the shift windows:
          (-1, -1)           --> off  (shift 0)
          (0,   0+dur)       --> night (shift 1)
          (8,   8+dur)       --> day   (shift 2)
          (16, 16+dur)       --> evening (shift 3)
        """
        violations = []

        OFF_SHIFT   = 0
        NIGHT_SHIFT = 1
        DAYS_PER_WEEK = 7
        hours_per_slot = self.numIntervalsInDay // (self.numShifts - 1)

        def shift_of(e, d):
            begin, _ = sched[e][d]
            return OFF_SHIFT if begin == -1 else begin // hours_per_slot + 1

        def duration_of(e, d):
            begin, end = sched[e][d]
            return 0 if begin == -1 else end - begin

        employees = range(self.numEmployees)
        days      = range(self.numDays)
        shifts    = range(self.numShifts)

        # Daily duration bounds
        for e in employees:
            for d in days:
                dur = duration_of(e, d)
                s   = shift_of(e, d)
                if s == OFF_SHIFT:
                    if dur != 0:
                        violations.append(f"E{e+1} D{d}: off shift but duration={dur}")
                else:
                    if dur < self.minConsecutiveWork:
                        violations.append(f"E{e+1} D{d}: duration {dur} < minConsecutiveWork {self.minConsecutiveWork}")
                    if dur > self.maxDailyWork:
                        violations.append(f"E{e+1} D{d}: duration {dur} > maxDailyWork {self.maxDailyWork}")

        # Min employees per shift per day 
        for d in days:
            counts = {s: sum(1 for e in employees if shift_of(e, d) == s) for s in shifts}
            for s in shifts:
                demand = self.minDemandDayShift[d][s]
                if counts[s] < demand:
                    violations.append(
                        f"D{d} shift {s}: {counts[s]} employees < demand {demand}"
                    )

        # Min daily operation 
        for d in days:
            total = sum(duration_of(e, d) for e in employees)
            if total < self.minDailyOperation:
                violations.append(
                    f"D{d}: total hours {total} < minDailyOperation {self.minDailyOperation}"
                )

        # Training phase: AllDifferent across first numShifts days
        for e in employees:
            labels = [shift_of(e, d) for d in range(self.numShifts)]
            if len(set(labels)) != self.numShifts:
                violations.append(
                    f"E{e+1} training phase: shift labels not all-different: {labels}"
                )

        # 5. Weekly work-hour bounds
        num_full_weeks = self.numDays // DAYS_PER_WEEK
        for e in employees:
            for w in range(num_full_weeks):
                week_days = range(w * DAYS_PER_WEEK, (w + 1) * DAYS_PER_WEEK)
                total = sum(duration_of(e, d) for d in week_days)
                if total < self.minWeeklyWork:
                    violations.append(
                        f"E{e+1} week {w}: {total}h < minWeeklyWork {self.minWeeklyWork}"
                    )
                if total > self.maxWeeklyWork:
                    violations.append(
                        f"E{e+1} week {w}: {total}h > maxWeeklyWork {self.maxWeeklyWork}"
                    )

        # Max consecutive night shifts
        for e in employees:
            for d in range(self.numDays - self.maxConsecutiveNightShift):
                window = sum(
                    1 for k in range(self.maxConsecutiveNightShift + 1)
                    if shift_of(e, d + k) == NIGHT_SHIFT
                )
                if window > self.maxConsecutiveNightShift:
                    violations.append(
                        f"E{e+1} D{d}-D{d+self.maxConsecutiveNightShift}: "
                        f"{window} consecutive nights > {self.maxConsecutiveNightShift}"
                    )

        # Max total night shifts
        for e in employees:
            total = sum(1 for d in days if shift_of(e, d) == NIGHT_SHIFT)
            if total > self.maxTotalNightShift:
                violations.append(
                    f"E{e+1}: {total} total night shifts > maxTotalNightShift {self.maxTotalNightShift}"
                )

        return violations


    def analyze_solution(self, sched: list, sched_name: str, warnings_file: str = "warnings.json") -> list[dict]:
        """
        Performs quality analysis on a valid solution and emits warnings
        as JS-style records to a shared file. Each record has the form:
          { "schedule": "14_14.sched", "type": "...", "message": "..." }

        Checks performed:
          1. Shift rotation fairness across employees
          2. Front-loading of work hours (early days vs later days)
          3. Even distribution of working employees per day
          4. Backup (off) employees per day
          5. Evening→night cross-day transitions
          6. Hours-per-week statistics (mean, variance) — the "under 40h" signal
        """
        warnings = []
        OFF_SHIFT = 0
        NIGHT_SHIFT = 1
        DAY_SHIFT = 2
        EVENING_SHIFT = 3
        DAYS_PER_WEEK = 7
        hours_per_slot = self.numIntervalsInDay // (self.numShifts - 1)
        SHIFT_NAMES = {0: "off", 1: "night", 2: "day", 3: "evening"}

        employees = range(self.numEmployees)
        days = range(self.numDays)

        def shift_of(e, d):
            begin, _ = sched[e][d]
            return OFF_SHIFT if begin == -1 else begin // hours_per_slot + 1

        def duration_of(e, d):
            begin, end = sched[e][d]
            return 0 if begin == -1 else end - begin

        def warn(wtype, msg, **extra):
            rec = {"schedule": sched_name, "type": wtype, "message": msg}
            rec.update(extra)
            warnings.append(rec)

        # ------------------------------------------------------------------ #
        # 1. Shift rotation fairness                                          #
        # How evenly are shift types distributed across employees?            #
        # ------------------------------------------------------------------ #
        shift_counts = np.zeros((self.numEmployees, self.numShifts), dtype=int)
        for e in employees:
            for d in days:
                shift_counts[e][shift_of(e, d)] += 1

        # For each work shift (1,2,3), compute CV (std/mean) across employees
        for s in range(1, self.numShifts):
            col = shift_counts[:, s].astype(float)
            mean_s = col.mean()
            if mean_s > 0:
                cv = col.std() / mean_s
                if cv > 0.5:
                    warn("rotation_imbalance",
                         f"{SHIFT_NAMES.get(s, s)} shift poorly rotated: "
                         f"counts range {int(col.min())}-{int(col.max())} "
                         f"(mean={mean_s:.1f}, CV={cv:.2f})",
                         shift=s, cv=round(cv, 3))

        # Overall work-day count fairness (days not off)
        work_days = np.array([sum(1 for d in days if shift_of(e, d) != OFF_SHIFT) for e in employees])
        if work_days.mean() > 0:
            cv = work_days.std() / work_days.mean()
            if cv > 0.15:
                warn("workday_imbalance",
                     f"Working days unevenly distributed: range {work_days.min()}-{work_days.max()} "
                     f"(mean={work_days.mean():.1f}, CV={cv:.2f})",
                     cv=round(cv, 3))

        # ------------------------------------------------------------------ #
        # 2. Front-loading of work hours                                      #
        # Compare avg daily hours in first half vs second half of schedule    #
        # ------------------------------------------------------------------ #
        daily_totals = np.array([sum(duration_of(e, d) for e in employees) for d in days])
        mid = self.numDays // 2
        first_half_avg = daily_totals[:mid].mean()
        second_half_avg = daily_totals[mid:].mean()
        overall_avg = daily_totals.mean()
        if overall_avg > 0:
            ratio = first_half_avg / second_half_avg if second_half_avg > 0 else float('inf')
            if ratio > 1.3:
                warn("front_loaded",
                     f"Work hours front-loaded: first half avg={first_half_avg:.1f}h, "
                     f"second half avg={second_half_avg:.1f}h (ratio={ratio:.2f})",
                     first_half_avg=round(first_half_avg, 1),
                     second_half_avg=round(second_half_avg, 1))
            elif ratio < 0.77:
                warn("back_loaded",
                     f"Work hours back-loaded: first half avg={first_half_avg:.1f}h, "
                     f"second half avg={second_half_avg:.1f}h (ratio={ratio:.2f})",
                     first_half_avg=round(first_half_avg, 1),
                     second_half_avg=round(second_half_avg, 1))

        # Per-day breakdown for uneven days
        if overall_avg > 0:
            day_cv = daily_totals.std() / overall_avg
            if day_cv > 0.2:
                warn("uneven_daily_hours",
                     f"Daily total hours vary significantly: "
                     f"range {daily_totals.min()}-{daily_totals.max()} "
                     f"(mean={overall_avg:.1f}, CV={day_cv:.2f})",
                     daily_totals=daily_totals.tolist())

        # ------------------------------------------------------------------ #
        # 3. Even distribution of working employees per day                   #
        # ------------------------------------------------------------------ #
        workers_per_day = np.array([
            sum(1 for e in employees if shift_of(e, d) != OFF_SHIFT) for d in days
        ])
        if workers_per_day.mean() > 0:
            cv = workers_per_day.std() / workers_per_day.mean()
            if cv > 0.15:
                warn("uneven_staffing",
                     f"Working employees per day uneven: "
                     f"range {workers_per_day.min()}-{workers_per_day.max()} "
                     f"(mean={workers_per_day.mean():.1f}, CV={cv:.2f})",
                     per_day=workers_per_day.tolist())

        # ------------------------------------------------------------------ #
        # 4. Backup (off) employees per day                                   #
        # ------------------------------------------------------------------ #
        off_per_day = self.numEmployees - workers_per_day
        days_without_backup = [int(d) for d in days if off_per_day[d] == 0]
        if days_without_backup:
            warn("no_backup",
                 f"No off-duty (backup) employees on {len(days_without_backup)} day(s): "
                 f"days {days_without_backup}",
                 days=days_without_backup)

        min_off = int(off_per_day.min())
        warn("backup_summary",
             f"Off-duty employees per day: min={min_off}, max={int(off_per_day.max())}, "
             f"mean={off_per_day.mean():.1f}",
             min_off=min_off, max_off=int(off_per_day.max()),
             per_day=off_per_day.tolist())

        # ------------------------------------------------------------------ #
        # 5. Evening→Night cross-day transitions                              #
        # Employee works evening on day d then night on day d+1               #
        # ------------------------------------------------------------------ #
        evening_night_transitions = []
        for e in employees:
            for d in range(self.numDays - 1):
                if shift_of(e, d) == EVENING_SHIFT and shift_of(e, d + 1) == NIGHT_SHIFT:
                    evening_night_transitions.append((e, d))

        if evening_night_transitions:
            details = [f"E{e+1} D{d}->D{d+1}" for e, d in evening_night_transitions]
            warn("evening_to_night",
                 f"{len(evening_night_transitions)} evening->night transition(s) "
                 f"(minimal rest): {', '.join(details)}",
                 count=len(evening_night_transitions),
                 transitions=details)

        # ------------------------------------------------------------------ #
        # 6. Hours-per-week statistics (the "under 40h" signal)               #
        # ------------------------------------------------------------------ #
        num_full_weeks = self.numDays // DAYS_PER_WEEK
        if num_full_weeks > 0:
            weekly_hours = np.zeros((self.numEmployees, num_full_weeks))
            for e in employees:
                for w in range(num_full_weeks):
                    week_days = range(w * DAYS_PER_WEEK, (w + 1) * DAYS_PER_WEEK)
                    weekly_hours[e][w] = sum(duration_of(e, d) for d in week_days)

            # Per-week stats
            for w in range(num_full_weeks):
                col = weekly_hours[:, w]
                warn("weekly_hours_stats",
                     f"Week {w}: mean={col.mean():.1f}h, std={col.std():.1f}h, "
                     f"min={col.min():.0f}h, max={col.max():.0f}h, "
                     f"variance={col.var():.1f}",
                     week=w,
                     mean=round(float(col.mean()), 1),
                     std=round(float(col.std()), 1),
                     variance=round(float(col.var()), 1),
                     min=float(col.min()),
                     max=float(col.max()))

            # Overall across all weeks
            all_weekly = weekly_hours.flatten()
            warn("overall_hours_stats",
                 f"All weeks: mean={all_weekly.mean():.1f}h, std={all_weekly.std():.1f}h, "
                 f"variance={all_weekly.var():.1f}, "
                 f"range=[{all_weekly.min():.0f}, {all_weekly.max():.0f}]",
                 mean=round(float(all_weekly.mean()), 1),
                 std=round(float(all_weekly.std()), 1),
                 variance=round(float(all_weekly.var()), 1),
                 min=float(all_weekly.min()),
                 max=float(all_weekly.max()))

            # Employees consistently under a threshold (e.g. 40h)
            UNDER_THRESHOLD = 40
            always_under = [int(e) for e in employees
                            if all(weekly_hours[e][w] < UNDER_THRESHOLD for w in range(num_full_weeks))]
            if always_under:
                warn("under_threshold",
                     f"{len(always_under)}/{self.numEmployees} employees always under "
                     f"{UNDER_THRESHOLD}h/week: E{', E'.join(str(e+1) for e in always_under)}",
                     threshold=UNDER_THRESHOLD,
                     count=len(always_under),
                     employees=[e+1 for e in always_under])

        # Write warnings to shared file, consolidated by schedule
        try:
            existing = {}
            try:
                with open(warnings_file, "r") as f:
                    existing = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            # Strip the "schedule" key from each record (it's now the dict key)
            existing[sched_name] = [
                {k: v for k, v in w.items() if k != "schedule"} for w in warnings
            ]
            with open(warnings_file, "w") as f:
                json.dump(existing, f, indent=2)
        except IOError as e:
            print(f"Warning: could not write to {warnings_file}: {e}", file=sys.stderr)
        except IOError as e:
            print(f"Warning: could not write to {warnings_file}: {e}", file=sys.stderr)

        return warnings


    def prettyPrint(self, numEmployees, numDays, sched):
        """
        Poor man's Gantt chart.
        Displays the employee schedules on the command line. 
        Each row corresponds to a single employee. 
        A "+" refers to a working hour and "." means no work
        The shifts are separated with a "|"
        The days are separated with "||"
        
        This might help you analyze your solutions. 
        
        @param numEmployees the number of employees
        @param numDays the number of days
        @param sched sched[e][d] = (begin, end) hours for employee e on day d
        """
        for e in range(numEmployees):
            print(f"E{e+1}: ", end="")
            if e < 9: print(" ", end="")
            for d in range(numDays):
                begin = sched[e][d][0]
                end = sched[e][d][1]
                for i in range(self.numIntervalsInDay):
                    if i % 8 == 0: print("|", end="")
                    if begin != end and i >= begin and i < end:
                         print("+", end="")
                    else:
                         print(".", end="")
                print("|", end="")
            print(" ")

    def generateVisualizerInput(self, numEmployees, numDays, sched):
        solString = f"{numDays} {numEmployees}\n"
        for d in range(numDays):
            for e in range(numEmployees):
                solString += f"{sched[e][d][0]} {sched[e][d][1]}\n"

        fileName = f"{numDays}_{numEmployees}_sol.txt"
        try:
            with open(fileName, "w") as fl:
                fl.write(solString)
            print(f"File created: {fileName}")
        except IOError as e:
            print(f"An error occured: {e}")
