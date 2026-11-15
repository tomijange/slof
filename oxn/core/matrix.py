"""
Purpose: Expands the matrix section of an experiment spec into one concrete spec per variant.
Functionality: Validates the matrix with pydantic, builds every combination of levels and fills the ${{ ... }}
    placeholders of the rest of the spec.
Connection: Used by validation.py on the raw YAML, before the spec model parses each variant.

    matrix:
      sampling: [5.0, 10.0]                 # levels named by their value
      storage:                              # named levels, the values can be any YAML
        memory: {values: deployments/values/values_opentelemetry_demo.yaml, steps: []}
        elasticsearch: {values: ..., steps: [{manifests: {paths: [k8s/elasticsearch/]}}]}
    experiment:
      deployment:
        steps:
          - ${{ storage.steps }}            # a list is spliced into the surrounding list
          - helm: {..., values: ["${{ storage.values }}"]}

A spec without a matrix is a single variant without levels.
"""

import copy
import itertools
import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Dict, List, Sequence, Set, Tuple

from pydantic import BeforeValidator, Field, RootModel, StringConstraints

MATRIX_KEY = "matrix"
"""Top level key of the matrix section, next to experiment"""

PLACEHOLDER_PATTERN = r"\$\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_-]+)*)\s*\}\}"
"""A placeholder like ${{ storage.values }}, also valid as a JavaScript regex for the JSON schema"""
AXIS_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
LEVEL_PATTERN = r"^[A-Za-z0-9_.+-]+$"
"""Level names end up in store keys and on the command line, so they stay free of /, spaces and separators"""

_PLACEHOLDER = re.compile(PLACEHOLDER_PATTERN)
_SCALARS = (str, int, float, bool)


class MatrixError(Exception):
    """A placeholder or a selection does not match the matrix"""


def _text(value: Any) -> str:
    """How a scalar is written in level names and inside longer strings"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _name_list_levels(levels: Any) -> Any:
    """Turn a list of levels into a mapping that names each level by its value"""
    if not isinstance(levels, list):
        return levels
    for value in levels:
        if not isinstance(value, _SCALARS):
            raise ValueError(f"{value!r} is not a number, string or boolean, use a mapping to name such levels")
    return {_text(value): value for value in levels}


AxisName = Annotated[str, StringConstraints(pattern=AXIS_PATTERN)]
LevelName = Annotated[str, StringConstraints(pattern=LEVEL_PATTERN)]
Levels = Annotated[Dict[LevelName, Any], BeforeValidator(_name_list_levels), Field(min_length=1)]


class Matrix(RootModel[Annotated[Dict[AxisName, Levels], Field(min_length=1)]]):
    """The matrix section: axes with their levels, by name"""

    def variants(self) -> List["Variant"]:
        """Every combination of levels, in the order of the axes and their levels"""
        axes = self.root
        return [
            Variant(levels=dict(zip(axes, names)), values={axis: axes[axis][name] for axis, name in zip(axes, names)})
            for names in itertools.product(*axes.values())
        ]


@dataclass(frozen=True)
class Variant:
    """One combination of levels, one per axis"""

    levels: Dict[str, str] = field(default_factory=dict)
    """The name of the level of every axis"""
    values: Dict[str, Any] = field(default_factory=dict)
    """What the placeholders of every axis resolve to"""

    @property
    def id(self) -> str:
        """Like sampling=10.0,storage=memory, empty for a spec without a matrix"""
        return ",".join(f"{axis}={name}" for axis, name in self.levels.items())

    @property
    def factors(self) -> Dict[str, Any]:
        """The level of every axis as recorded with the results: the value of a list level, else its name"""
        return {
            axis: self.values[axis] if _text(self.values[axis]) == name else name for axis, name in self.levels.items()
        }

    def key(self, spec_path: str) -> str:
        """The experiment key of the variant: the spec path, followed by the variant id in brackets"""
        return f"{spec_path}[{self.id}]" if self.levels else spec_path


def expand(raw: Dict[str, Any], only: Sequence[str] = ()) -> List[Tuple[Variant, Dict[str, Any]]]:
    """
    The selected variants of a raw spec, each with its raw spec without the matrix and with the placeholders filled in

    only holds selections like sampling=10.0. Selections of the same axis are alternatives, selections of different
    axes must all match. Raises a pydantic ValidationError for an invalid matrix, and a MatrixError for a placeholder
    or selection that does not fit it.
    """
    matrix = Matrix.model_validate(raw[MATRIX_KEY]) if MATRIX_KEY in raw else None
    body = {key: value for key, value in raw.items() if key != MATRIX_KEY}
    axes = matrix.root if matrix is not None else {}
    variants = _select(axes, matrix.variants() if matrix is not None else [Variant()], only)
    used: Set[str] = set()
    expanded = [(variant, _substitute(body, variant.values, [], used)) for variant in variants]
    unused = [axis for axis in axes if axis not in used]
    if unused:
        raise MatrixError(f"No placeholder uses the axis {', '.join(unused)}")
    return expanded


def _select(axes: Dict[str, Dict[str, Any]], variants: List[Variant], only: Sequence[str]) -> List[Variant]:
    wanted: Dict[str, Set[str]] = {}
    for selection in only:
        axis, _, name = selection.partition("=")
        if name not in axes.get(axis, {}):
            known = "; ".join(f"{axis}: {', '.join(levels)}" for axis, levels in axes.items())
            raise MatrixError(
                f"--only {selection}: expected AXIS=LEVEL, "
                + (f"the matrix has {known}" if axes else "the spec has no matrix")
            )
        wanted.setdefault(axis, set()).add(name)
    return [variant for variant in variants if all(variant.levels[axis] in names for axis, names in wanted.items())]


def _resolve(reference: str, values: Dict[str, Any], where: str, used: Set[str]) -> Any:
    axis, *keys = reference.split(".")
    if axis not in values:
        known = f"the matrix has {', '.join(values)}" if values else "the spec has no matrix"
        raise MatrixError(f"{where}: unknown axis {axis}, {known}")
    used.add(axis)
    value = values[axis]
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise MatrixError(f"{where}: ${{{{ {reference} }}}} does not exist in every level of {axis}")
        value = value[key]
    return copy.deepcopy(value)


def _substitute(node: Any, values: Dict[str, Any], path: List[Any], used: Set[str]) -> Any:
    """
    Fill the placeholders in node

    A placeholder that is a whole value becomes the value of the level, with its type. In a list, a value that is a
    list itself is spliced in. Inside a longer string, the value has to be a scalar and is inserted as text.
    """
    where = ".".join(map(str, path))
    if isinstance(node, dict):
        for key in node:
            if isinstance(key, str) and "${{" in key:
                raise MatrixError(f"{where}: placeholders are only filled in values, not in the key {key}")
        return {key: _substitute(value, values, [*path, key], used) for key, value in node.items()}
    if isinstance(node, list):
        items: List[Any] = []
        for index, item in enumerate(node):
            value = _substitute(item, values, [*path, index], used)
            if isinstance(item, str) and _PLACEHOLDER.fullmatch(item.strip()) and isinstance(value, list):
                items.extend(value)
            else:
                items.append(value)
        return items
    if not isinstance(node, str):
        return node
    whole = _PLACEHOLDER.fullmatch(node.strip())
    if whole:
        return _resolve(whole.group(1), values, where, used)

    def interpolate(match: re.Match) -> str:
        value = _resolve(match.group(1), values, where, used)
        if not isinstance(value, _SCALARS):
            raise MatrixError(f"{where}: inside a longer string, {match.group(0)} has to be a scalar")
        return _text(value)

    text = _PLACEHOLDER.sub(interpolate, node)
    if "${{" in text:
        raise MatrixError(f"{where}: invalid placeholder in {node!r}, expected one like ${{{{ sampling }}}}")
    return text
