"""
Purpose: Implements the treatments that can be applied during experiments.
Functionality: runtime/ holds treatments injected while the load runs, compile_time/ holds treatments
that change the SUE's configuration before the load starts. One module per treatment.
Connection: The runner maps the action keys of the experiment spec to these classes.
"""
