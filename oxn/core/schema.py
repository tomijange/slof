"""
Purpose: Builds the JSON schema of experiment specs, for completion and checks in editors.
Functionality: Starts from the pydantic schema of the spec model and of the params models of the treatment registry,
    and changes it to the form of the YAML files: entries like `- system_CPU: {...}`, params that depend on the action,
    the matrix section and ${{ ... }} placeholders in place of any value.
Connection: oxn schema writes it to schema.json, which every spec names in a yaml-language-server comment.
    oxn itself validates specs with the pydantic models, not with this schema.
"""

import inspect
import json
from typing import Any, Dict, List

from pydantic.json_schema import models_json_schema

from oxn.core.matrix import AXIS_PATTERN, LEVEL_PATTERN, PLACEHOLDER_PATTERN
from oxn.models.experiment_spec import ExperimentSpec
from oxn.treatments.registry import TreatmentRegistry

PLACEHOLDER = {
    "type": "string",
    "pattern": rf"^\s*{PLACEHOLDER_PATTERN}\s*$",
    "description": "A placeholder, filled with the value of a level of the matrix",
}

MATRIX = {
    "type": "object",
    "description": "Axes to compare, oxn runs one variant for every combination of their levels. "
    "The experiment section uses them as ${{ axis }} or ${{ axis.key }}.",
    "minProperties": 1,
    "propertyNames": {"pattern": AXIS_PATTERN},
    "additionalProperties": {
        "anyOf": [
            {
                "type": "array",
                "description": "Levels named by their value, like [5.0, 10.0]",
                "minItems": 1,
                "items": {"type": ["string", "number", "boolean"]},
            },
            {
                "type": "object",
                "description": "Named levels, whose values can be any YAML",
                "minProperties": 1,
                "propertyNames": {"pattern": LEVEL_PATTERN},
            },
        ]
    },
}


def _ref(name: str) -> Dict[str, Any]:
    return {"$ref": f"#/$defs/{name}"}


def _entry(value: Dict[str, Any], description: str) -> Dict[str, Any]:
    """A list entry of the YAML form `- name: {...}`: a mapping with one key, the name"""
    return {
        "type": "object",
        "description": description,
        "minProperties": 1,
        "maxProperties": 1,
        "additionalProperties": value,
    }


def _drop_property(definition: Dict[str, Any], name: str) -> None:
    """Remove a field that the spec does not write itself, like the name of an entry, which is its key"""
    definition["properties"].pop(name)
    if name in definition.get("required", []):
        definition["required"].remove(name)


def _summary(treatment_class: type) -> str:
    return (inspect.getdoc(treatment_class) or treatment_class.__name__).split("\n\n")[0]


def _allow_placeholders(node: Any) -> Any:
    """Accept a placeholder in place of every property value, list item and mapping value"""
    if isinstance(node, list):
        return [_allow_placeholders(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = {key: _allow_placeholders(value) for key, value in node.items()}

    def wrap(schema: Any) -> Any:
        if not isinstance(schema, dict):
            return schema
        wrapped = {"anyOf": [schema, _ref("Placeholder")]}
        # editors show the description of the field for a placeholder too
        for key in ("title", "description"):
            if key in schema:
                wrapped[key] = schema[key]
        return wrapped

    if isinstance(node.get("properties"), dict):
        node["properties"] = {key: wrap(value) for key, value in node["properties"].items()}
    for key in ("items", "additionalProperties"):
        if key in node:
            node[key] = wrap(node[key])
    return node


def spec_schema(registry: TreatmentRegistry) -> Dict[str, Any]:
    """The JSON schema of an experiment spec whose treatments come from registry"""
    actions: List[str] = list(registry.actions)
    params_models = {action: registry.params_model(action) for action in actions}
    models = [ExperimentSpec, *dict.fromkeys(params_models.values())]
    refs, schema = models_json_schema([(model, "validation") for model in models], ref_template="#/$defs/{model}")
    defs = schema["$defs"]

    for name in ("MetricResponseDescription", "TraceResponseDescription", "TreatmentDescription"):
        _drop_property(defs[name], "name")
    for name in ("HelmRelease", "Manifests"):
        _drop_property(defs[name], "kind")

    treatment = defs["TreatmentDescription"]
    treatment["properties"]["action"] = {
        "enum": actions,
        "description": "The treatment to run, see the params for each action",
    }
    treatment["properties"]["params"] = {"type": "object"}
    defs.pop("TreatmentParams", None)

    experiment = defs["Experiment"]["properties"]
    experiment["responses"] = {
        "type": "array",
        "description": "The values to record, one entry per response, named by its key",
        "items": _entry(
            {"anyOf": [_ref("MetricResponseDescription"), _ref("TraceResponseDescription")]},
            "A response, like `- system_CPU: {type: metric, ...}`",
        ),
    }
    experiment["treatments"] = {
        "type": "array",
        "description": "What to change, one entry per treatment, named by its key",
        "items": _entry(_ref("TreatmentDescription"), "A treatment, like `- delay_treatment: {action: delay, ...}`"),
    }
    defs["DeploymentDescription"]["properties"]["steps"] = {
        "type": "array",
        "description": "The ordered deployment steps",
        "items": {
            "type": "object",
            "description": "A Helm release or a folder of manifests",
            "properties": {"helm": _ref("HelmRelease"), "manifests": _ref("Manifests")},
            "additionalProperties": False,
            "minProperties": 1,
            "maxProperties": 1,
        },
    }

    defs = _allow_placeholders(defs)
    defs["Placeholder"] = PLACEHOLDER
    # added after the placeholders, so a placeholder as action does not select every branch
    defs["TreatmentDescription"]["allOf"] = [
        {
            "if": {"properties": {"action": {"const": action}}, "required": ["action"]},
            "then": {
                "description": _summary(registry.treatment_class(action)),
                "properties": {"params": refs[(params_models[action], "validation")]},
            },
        }
        for action in actions
    ]
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "oxn experiment spec",
        "description": "Generated by oxn schema from the spec model and the treatments, do not edit",
        "type": "object",
        "properties": {
            "matrix": MATRIX,
            "experiment": _ref("Experiment"),
        },
        "required": ["experiment"],
        "additionalProperties": False,
        "$defs": defs,
    }


def schema_text(registry: TreatmentRegistry) -> str:
    """The schema as it is written to the file"""
    return json.dumps(spec_schema(registry), indent=2) + "\n"
