"""
Purpose: Implements oxn plan.
Functionality: Describes the runs of an experiment spec and its matrix, with the load time of each variant, and
    prints the expanded spec of every variant on request.
Connection: Called by main.py with the variants that validation.py loaded.
"""

from typing import List

import yaml

from oxn.common.utils import time_string_to_seconds
from oxn.core.validation import ExperimentVariant


def format_duration(seconds: float) -> str:
    """Like 9h20m, 45m or 30s"""
    minutes, rest = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m{rest:02d}s" if rest else f"{minutes}m"
    return f"{rest}s"


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def describe_plan(path: str, variants: List[ExperimentVariant], times: int) -> str:
    """The runs that oxn <path> --times <times> would do, as text"""
    load_times = [time_string_to_seconds(experiment.spec.experiment.loadgen.run_time) for experiment in variants]
    total = sum(load_times) * times
    runs = len(variants) * times
    if variants[0].variant.levels:
        count = f"{_count(len(variants), 'variant')} x {_count(times, 'run')} = {_count(runs, 'run')}"
    else:
        count = f"no matrix, {_count(runs, 'run')}"
    lines = [f"{path}: {count}, {format_duration(total)} of load plus deployment and teardown"]
    if variants[0].variant.levels:
        width = max(len(experiment.variant.id) for experiment in variants)
        lines += [
            f"  {experiment.variant.id:<{width}}  {format_duration(load_time)}"
            for experiment, load_time in zip(variants, load_times)
        ]
        if times > 1:
            lines.append(f"Every round runs each variant once, in this order, {times} rounds")
    return "\n".join(lines)


def expanded_specs(variants: List[ExperimentVariant]) -> str:
    """The expanded spec of every variant as YAML documents, each headed by a comment with the variant id"""
    documents = []
    for experiment in variants:
        spec = yaml.safe_dump(experiment.raw, sort_keys=False, width=1000)
        header = f"# variant {experiment.variant.id}\n" if experiment.variant.levels else ""
        documents.append(f"---\n{header}{spec}")
    return "".join(documents)
