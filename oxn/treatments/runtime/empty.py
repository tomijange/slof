"""Treatments that only observe the SUE"""

import time

from oxn.common.utils import time_string_format_regex, time_string_to_seconds, validate_time_string
from oxn.models.treatment import RuntimeTreatment


class EmptyTreatment(RuntimeTreatment):
    """
    Empty treatment to represent a simple observation of response variables
    """

    def clean(self) -> None:
        pass

    def _transform_params(self) -> None:
        relative_time_string = self.config.get("duration")
        relative_time_seconds = time_string_to_seconds(relative_time_string)
        self.config["duration_seconds"] = relative_time_seconds

    def _validate_params(self) -> bool:
        bools = []
        for key, value in self.params().items():
            if (
                key
                in {
                    "duration",
                }
                and key not in self.config
            ):
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(f"Parameter {key} has to match {time_string_format_regex}")
                    bools.append(False)
        return all(bools)

    def inject(self) -> None:
        sleep_duration_seconds = self.config["duration_seconds"]
        time.sleep(sleep_duration_seconds)

    def params(self) -> dict:
        return {
            "duration": str,
        }

    def preconditions(self) -> bool:
        return True

    @property
    def action(self):
        return "empty"

    def _validate_orchestrator(self) -> bool:
        return True


class EmptyKubernetesTreatment(RuntimeTreatment):
    """
    Empty treatment to represent a simple observation of response variables
    """

    def clean(self) -> None:
        pass

    def _transform_params(self) -> None:
        relative_time_string = self.config.get("duration")
        relative_time_seconds = time_string_to_seconds(relative_time_string)
        self.config["duration_seconds"] = relative_time_seconds

    def _validate_params(self) -> bool:
        bools = []
        for key, value in self.params().items():
            if (
                key
                in {
                    "duration",
                }
                and key not in self.config
            ):
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(f"Parameter {key} has to match {time_string_format_regex}")
                    bools.append(False)
        return all(bools)

    def inject(self) -> None:
        sleep_duration_seconds = self.config["duration_seconds"]
        time.sleep(sleep_duration_seconds)

    def params(self) -> dict:
        return {
            "duration": str,
        }

    def preconditions(self) -> bool:
        return True

    @property
    def action(self):
        return "empty"

    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
