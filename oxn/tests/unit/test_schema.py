"""Test the JSON schema of experiment specs"""

import copy
import glob
import importlib.util
import os
import unittest

import yaml

from oxn.core.schema import schema_text, spec_schema
from oxn.models.treatment_params import TreatmentParams
from oxn.treatments.registry import TreatmentRegistry
from oxn.treatments.runtime import EmptyTreatment

HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None
"""jsonschema is only in requirements-dev.txt"""

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCHEMA_PATH = os.path.join(REPO_ROOT, "schema.json")


class SchemaFileTest(unittest.TestCase):
    def test_the_committed_schema_is_up_to_date(self):
        with open(SCHEMA_PATH) as fp:
            committed = fp.read()
        self.assertEqual(committed, schema_text(TreatmentRegistry()), "Run make schema")

    def test_every_spec_names_the_schema(self):
        for path in glob.glob(os.path.join(REPO_ROOT, "experiments", "*.yml")):
            with self.subTest(path=os.path.basename(path)), open(path) as fp:
                self.assertEqual(fp.readline(), "# yaml-language-server: $schema=../schema.json\n")

    def test_own_treatments_get_their_params(self):
        class OwnParams(TreatmentParams):
            level: int

        class OwnTreatment(EmptyTreatment):
            """Do something of our own"""

            action = "own"
            Params = OwnParams

        registry = TreatmentRegistry([OwnTreatment])
        treatment = spec_schema(registry)["$defs"]["TreatmentDescription"]
        self.assertIn("own", treatment["properties"]["action"]["anyOf"][0]["enum"])
        own = [
            branch["then"] for branch in treatment["allOf"] if branch["if"]["properties"]["action"]["const"] == "own"
        ]
        self.assertEqual(
            own, [{"description": "Do something of our own", "properties": {"params": {"$ref": "#/$defs/OwnParams"}}}]
        )


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema is not installed, see requirements-dev.txt")
class SchemaValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jsonschema

        schema = spec_schema(TreatmentRegistry())
        jsonschema.Draft7Validator.check_schema(schema)
        cls.validator = jsonschema.Draft7Validator(schema)
        with open(os.path.join(REPO_ROOT, "experiments", "test.yml")) as fp:
            cls.spec = yaml.safe_load(fp)

    def test_the_shipped_specs_and_their_matrices_are_valid(self):
        for path in sorted(glob.glob(os.path.join(REPO_ROOT, "experiments", "*.yml"))):
            with self.subTest(path=os.path.basename(path)), open(path) as fp:
                errors = [error.message for error in self.validator.iter_errors(yaml.safe_load(fp))]
                self.assertEqual(errors, [])

    def _error(self, change):
        """The best matching error and its location after change edits a copy of test.yml, None if it is valid"""
        spec = copy.deepcopy(self.spec)
        change(spec["experiment"], spec)
        from jsonschema.exceptions import best_match

        error = best_match(self.validator.iter_errors(spec))
        if error is None:
            return None
        return "/".join(map(str, error.absolute_path)), error.message

    def test_mistakes_are_found_where_they_are(self):
        delay = "treatments/0/delay_treatment"

        def treatment(experiment):
            return experiment["treatments"][0]["delay_treatment"]

        cases = [
            (lambda e, _: treatment(e).update(action="dealy"), f"experiment/{delay}/action"),
            (lambda e, _: treatment(e)["params"].update(delay_times="1ms"), f"experiment/{delay}/params"),
            (lambda e, _: treatment(e)["params"].pop("interface"), f"experiment/{delay}/params"),
            (lambda e, _: treatment(e)["params"].update(duration="5 minutes"), f"experiment/{delay}/params/duration"),
            (lambda e, _: e["loadgen"].update(max_users="many"), "experiment/loadgen/max_users"),
            (lambda e, _: e["responses"][0]["frontend_traces"].pop("type"), "experiment/responses/0/frontend_traces"),
            (lambda e, _: e["responses"][0].update(other={"type": "trace"}), "experiment/responses/0/other/type"),
            (lambda e, _: e["deployment"]["steps"].append({"kustomize": {}}), "experiment/deployment/steps/1"),
            (lambda _, s: s.update(experimnet={}), ""),
            (lambda _, s: s.update(matrix={"1a": [1]}), "matrix"),
        ]
        for change, location in cases:
            with self.subTest(location=location):
                error = self._error(change)
                self.assertIsNotNone(error)
                assert error is not None
                self.assertEqual(error[0], location, error[1])

    def test_placeholders_are_accepted_for_any_value(self):
        def change(experiment, spec):
            spec["matrix"] = {"duration": ["1m", "2m"], "steps": {"none": []}}
            experiment["treatments"][0]["delay_treatment"]["params"]["duration"] = "${{ duration }}"
            experiment["loadgen"]["max_users"] = "${{ users }}"
            experiment["deployment"]["steps"].insert(0, "${{ steps }}")

        self.assertIsNone(self._error(change))
