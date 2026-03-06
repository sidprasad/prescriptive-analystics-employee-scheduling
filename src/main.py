import json
from argparse import ArgumentParser
from pathlib import Path
from cpinstance import CPInstance
from model_timer import Timer

def main():
    parser = ArgumentParser()
    parser.add_argument("input_file", type=str)
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        help="Time limit in seconds (default: none)",
    )
    args = parser.parse_args()

    input_file = Path(args.input_file)
    filename = input_file.name

    instance = CPInstance(str(input_file))
    timer = Timer()
    timer.start()
    is_solution, n_fails, schedule = instance.solve(time_limit_seconds=args.time_limit)
    timer.stop()

    resultdict = {}
    resultdict["Instance"] = filename
    resultdict["Time"] = round(timer.getTime(), 2)
    resultdict["Result"] = str(n_fails)
    # Format: flat space-separated string of begin end pairs, employee by employee, day by day
    if is_solution and schedule:
        parts = []
        for e in range(len(schedule)):
            for d in range(len(schedule[e])):
                parts.append(str(schedule[e][d][0]))
                parts.append(str(schedule[e][d][1]))
        resultdict["Solution"] = " ".join(parts)

    # Pretty prints solution, uncomment to use
    # if is_solution:
    #     instance.prettyPrint(instance.numEmployees, instance.numDays, schedule)
    #     instance.generateVisualizerInput(instance.numEmployees, instance.numDays, schedule)
    print(json.dumps(resultdict))

if __name__ == "__main__":
    main()
