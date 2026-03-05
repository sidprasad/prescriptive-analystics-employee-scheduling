from __future__ import annotations

import sys
from typing import Optional, List, Tuple

import numpy as np
from ortools.constraint_solver import pywrapcp



class CPInstance:
    # BUSINESS parameters
    numWeeks: int ## SP: Is it days + weeks or either?
    numDays: int
    numEmployees: int
    numShifts: int  ## The off shift is denoted by 0 while work shifts, night, day, and evening are denoted by 1, 2, and 3 respectively. 
    numIntervalsInDay: int ## In general the problem is for 3 intervals in a day (08:00 - 16:00, 16:00 - 00:00, and 00:00 - 08:00) but we want to be able to handle more general cases.
                            ## Notice that if the employee finished at 14:00, it would still count as a day shift.
    minDemandDayShift: list[list[int]]  ## e.g. minDemandDayShift[d][s] = 2 means that on day d at least 2 employees should be working shift s.
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
    ):
        """
        Employee Scheduling Model 
        """
        
        # Immutable truths.
        HOURS_PER_DAY = 24
        DAYS_PER_WEEK = 7

        # Other truths that are sort of enforced by the problem spec.
        DAY_SHIFT_START = 8  # first work shift always begins at 08:00

        OFF_SHIFT = 0  # shift label for "off" shift; the remaining numShifts-1 labels are for actual work shifts.

        # Build shift windows: Its hard to be generic with these, since 
        # we have specific claims about 'night' shift and ''day shift''
        # Work shifts cycle starting from 08:00 so that:
        #.  shift 0 = off.
        #   shift 1 = day      08:00 – 16:00 ## TODO: How do we make DAY GENERIC?
        #   shift 2 = evening  16:00 – 00:00  
        #   shift 3 = night    00:00 – 08:00

        # shift 0 is "off"; the remaining numShifts-1 are the actual work shifts.
        num_work_shifts = self.numShifts - 1
        if num_work_shifts <= 0:
            raise ValueError("Expected at least one working shift in addition to the off shift.")
        if HOURS_PER_DAY % num_work_shifts != 0: 
            raise ValueError("Working shifts must partition the day into equal-length slots.")

        hours_per_shift_slot = HOURS_PER_DAY // num_work_shifts

        ## Shift windows is a list of the start and end times for each shift, indexed by shift label.
        shift_windows = [(0, 0)]  # shift 0: off
        for shift_idx in range(num_work_shifts):
            start = (DAY_SHIFT_START + shift_idx * hours_per_shift_slot) % HOURS_PER_DAY
            end = start + hours_per_shift_slot
            shift_windows.append((start, end))
        
        self.solver = pywrapcp.Solver("EmployeeScheduling")

        # Index sets used throughout the model, so we don't have to write range(...) everywhere.
        shifts = list(range(self.numShifts))
        days = list(range(self.numDays))
        employees = list(range(self.numEmployees))

        # variables

        # Expand each shift into all legal concrete assignments within its time window.
        # Enumerate every legal (shift, begin, finish) triple upfront as a Python list.
        # This pre-computation keeps the CP model small: the solver only sees one integer
        # variable per (employee, day) instead of separate begin/end/hours variables.
        # Each tuple is (shift_label, begin_hour, finish_hour, hours_worked).
        # The off shift (s=0) has no time window so it gets the sentinel (-1, -1, 0).


        # Flat lists indexed by option id — used as lookup tables inside Element constraints.
        # solver.Element requires plain int lists, so we build four parallel arrays directly.
        option_shift, option_begin, option_end, option_hours = [], [], [], []
        for s in shifts:
            if s == OFF_SHIFT:
                option_shift.append(s); option_begin.append(-1); option_end.append(-1); option_hours.append(0)
                continue

            start, end = shift_windows[s]
            for begin in range(start, end):
                min_finish = begin + self.minConsecutiveWork
                max_finish = min(begin + self.maxDailyWork, end)
                for finish in range(min_finish, max_finish + 1):
                    option_shift.append(s); option_begin.append(begin); option_end.append(finish); option_hours.append(finish - begin)

        num_options = len(option_shift)

        # Main decision variable: daily_assignment[employee][day] is an index into the option arrays.
        # Choosing its value simultaneously fixes the shift label, start time, end time, and hours
        # worked for employee e on day d.
        daily_assignment = [
            [
                self.solver.IntVar(0, num_options - 1, f"assignment_{e}_{d}")
                for d in days
            ]
            for e in employees
        ]

        # OR-Tools Element constraints to derive employee shift attributes from the decision variable.
        def elem(table, var):
            # solver.Element(table, index_var) creates an IntExpr whose value equals table[index_var].
            # This "looks up" attributes of the chosen option inside the CP model.
            return self.solver.Element(table, var)

        ## shift_of[employee][day] is the shift label for that employee and day.
        shift_of = [[elem(option_shift, daily_assignment[e][d]) for d in days] for e in employees]
        ## begin_of[employee][day] is the start time for that employee and day.
        begin_of = [[elem(option_begin, daily_assignment[e][d]) for d in days] for e in employees]
        ## end_of[employee][day] is the finish time for that employee and day.
        end_of   = [[elem(option_end,   daily_assignment[e][d]) for d in days] for e in employees]
        ## hours_of[employee][day] is the hours worked for that employee and day.
        hours_of = [[elem(option_hours, daily_assignment[e][d]) for d in days] for e in employees]

        # IntVar copies of shift_of, needed because Element with a variable index
        # requires an IntVar array (not IntExpr array).
        shift_var = [
            [self.solver.IntVar(0, self.numShifts - 1, f"shift_{e}_{d}") for d in days]
            for e in employees
        ]
        for e in employees:
            for d in days:
                self.solver.Add(shift_var[e][d] == shift_of[e][d])

        # The night shift is the last work shift (window starting at 00:00, index = num_work_shifts).
        ## THis is an attempt to be generic about the night shift. However, we still have
        ## other hard coded claims, so I'm dubious about how much this actually helps with generality.
        NIGHT_SHIFT = num_work_shifts


        # constraints

        #### Business Constraints ###

        # Each shift on each day must have at least the minimum required number of employees.

        for d in days:
            for s in shifts:
                demand = self.minDemandDayShift[d][s] ## We assume this encodes something about off?
                ## TODO: WHat if demand IS 0? What should we do?
                if demand > 0:
                    # IsEqualCstVar returns a 0/1 IntVar that is 1 iff shift_of[e][d] == s,
                    # so Sum(...) counts how many employees are on shift s on day d.
                    count = self.solver.Sum(
                        [self.solver.IsEqualCstVar(shift_of[e][d], s) for e in employees]
                    )
                    self.solver.Add(count >= demand)

        # Total hours worked by all employees on a given day must reach minDailyOperation.
        ## employees assigned to the off shift have hours_of[e][d] == 0 for that day, so they don't contribute to the sum.
        for d in days:
            self.solver.Add(
                self.solver.Sum([hours_of[e][d] for e in employees]) >= self.minDailyOperation
            )

        ### Training Phase Constraints ###

        # Each employee has a training_start day; their training spans numShifts consecutive days.
        # During training, each shift label appears exactly once (AllDifferent).
        training_start = [
            self.solver.IntVar(0, self.numDays - self.numShifts, f"train_start_{e}")
            for e in employees
        ]

        for e in employees:
            training_shift_vars = []
            for k in range(self.numShifts):
                # The actual day for training offset k
                day_var = self.solver.IntVar(0, self.numDays - 1, f"train_day_{e}_{k}")
                self.solver.Add(day_var == training_start[e] + k)
                # Look up the shift label on that day using the IntVar array
                train_shift = self.solver.Element(shift_var[e], day_var)
                training_shift_vars.append(train_shift)
            self.solver.Add(self.solver.AllDifferent(training_shift_vars))

        # Symmetry breaking: employees are interchangeable, so we impose an ordering
        # on training start days.
        for e in range(self.numEmployees - 1):
            self.solver.Add(training_start[e] <= training_start[e + 1])

        # Employees cannot work before their training starts — must be off shift.
        ## TODO: Is OFF shift the right choice? It feels like they shouldnt be scheduled AT ALL?
        for e in employees:
            for d in days:
                # If d < training_start[e], force off shift.
                # (d < training_start[e]) is rewritten as (training_start[e] > d),
                # which is a 0/1 boolean expression. We use it to imply shift must be OFF_SHIFT.
                self.solver.Add(
                    (shift_of[e][d] == OFF_SHIFT) >= (training_start[e] > d)
                )
        ### Employee Constraints ###

        # Max daily work hours: already enforced structurally — only options with
        # (finish - begin) <= maxDailyWork were added to assignment_options.

        # Weekly work hour bounds.
        # Enforce weekly hour bounds for each complete 7-day week.
        # Partial trailing weeks (if numDays % 7 != 0) are ignored.
        num_full_weeks = self.numDays // DAYS_PER_WEEK
        for e in employees:
            for w in range(num_full_weeks):
                week_days = list(range(w * DAYS_PER_WEEK, (w + 1) * DAYS_PER_WEEK))
                weekly_hours = self.solver.Sum([hours_of[e][d] for d in week_days])
                self.solver.Add(weekly_hours <= self.maxWeeklyWork)
                self.solver.Add(weekly_hours >= self.minWeeklyWork)

        # Sliding window of width (maxConsecutiveNightShift + 1) days: at most
        # maxConsecutiveNightShift of those days can be night shifts.
        for e in employees:
            for d in range(self.numDays - self.maxConsecutiveNightShift):
                consec_nights = self.solver.Sum(
                    [self.solver.IsEqualCstVar(shift_of[e][d + k], NIGHT_SHIFT)
                     for k in range(self.maxConsecutiveNightShift + 1)]
                )
                self.solver.Add(consec_nights <= self.maxConsecutiveNightShift)

        # Max total night shifts.
        for e in employees:
            total_nights = self.solver.Sum(
                [self.solver.IsEqualCstVar(shift_of[e][d], NIGHT_SHIFT) for d in days]
            )
            self.solver.Add(total_nights <= self.maxTotalNightShift)

        # Search phase: decide training start days first, then assign shifts.
        # Phase 1: fix when each employee's training begins (most constrained).
        phase1 = self.solver.Phase(
            training_start,
            self.solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
            self.solver.ASSIGN_MIN_VALUE,
        )
        # Phase 2: assign all daily shift options.
        all_vars = [daily_assignment[e][d] for e in employees for d in days]
        phase2 = self.solver.Phase(
            all_vars,
            self.solver.CHOOSE_MIN_SIZE_LOWEST_MIN,
            self.solver.ASSIGN_RANDOM_VALUE,
        )
        db = self.solver.Compose([phase1, phase2])

        # Luby restarts: the solver periodically abandons the current search tree and
        # restarts with a fresh random seed.
        ## TODO: Explore other restart strategies? Any citations on good restart starts?
        restart = self.solver.LubyRestart(100)  # base unit = 100 failures



        # Wire in wall-clock time limit.
        limits = [restart]
        if time_limit_seconds is not None:
            limits.append(self.solver.TimeLimit(int(time_limit_seconds * 1000))) # Max?
        self.solver.NewSearch(db, limits)

        if self.solver.NextSolution():
            schedule = [
                [
                    (option_begin[daily_assignment[e][d].Value()],
                     option_end[daily_assignment[e][d].Value()])
                    for d in days
                ]
                for e in employees
            ]
            self.solver.EndSearch()
            return True, self.solver.Failures(), schedule
        else:
            self.solver.EndSearch()
            return False, self.solver.Failures(), None
            

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
