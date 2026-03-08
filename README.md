EdStem: 

Hello everyone, 

Now that we have seen the Constraint Model (Inference) for the first part of Project 2, let's kick-off the second part of the project on Search Guidance. 

## First Part with Default Search

In the first part, we relied on the Default Search of the Google OR Tools Classical CP Solver (again, NOT the CP-SAT Solver!!)

# Google OR Tools Classical CP Solver and NOT CP-SAT
solver: pywrapcp.Solver = pywrapcp.Solver("CP Solver")

# Variables
# Constraints

# Solve with default search
db = self.solver.DefaultPhase(...)
solver.NewSearch(db)

if solver.NextSolution():
solution = ...


## Second Part with YOUR Search

In the second part, we will turn off the default phase and build our own custom heuristics. To do that, replace the decision builder (db): 

# Google OR Tools Classical CP Solver and NOT CP-SAT
solver: pywrapcp.Solver = pywrapcp.Solver("CP Solver")

# Variables 
# Constraints

# Solve with your search 
db = ... # YOUR Search Decisions and Custom Decision Builder HERE
solver.NewSearch(db)
if solver.NextSolution():
solution = ...


You can use the built-in variable/value selection strategies and/or write your own custom search goals. 

Have fun guiding the solver toward a feasible solutions 🥳

## Reports

In your reports, consider the persona of a store manager using the schedules. How would you evaluate the quality of these schedules? Are they good enough, ready-to-use? what's missing? etc. 

## Visualizer 

Feel free to make use of the visualization tool we provide to interpret results.
