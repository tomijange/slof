"""Change the probabilistic head sampling rate of the OpenTelemetry collector"""

import logging

from pydantic import Field, field_validator

from oxn.common.errors import OxnException
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import TreatmentParams

logger = logging.getLogger(__name__)


class HeadSamplingParams(TreatmentParams):
    """Params of kube_probl"""

    sampling_percentage: float = Field(ge=0, le=100)
    hash_seed: int

    @field_validator("sampling_percentage")
    @classmethod
    def _warn_on_high_rates(cls, value: float) -> float:
        if value > 20:
            logger.warning(
                f"Sampling percentage is set to {value}. High sampling rates can lead to high costs, "
                "performance issues and crashes."
            )
        return value


class ProbabilisticHeadSamplingTreatment(CompileTimeTreatment[HeadSamplingParams]):
    """
    Treatment to change the global sampling rate for head-based trace sampling in the OpenTelemetry collector

    use "increase(otelcol_processor_probabilistic_sampler_count_traces_sampled[1m])" in prometheus to see the change between sampled:true and sampled:false when changing the sampling percentage

    otel documentation: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/probabilisticsamplerprocessor

    """

    action = "kube_probl"
    Params = HeadSamplingParams

    def preconditions(self) -> bool:
        """Check that the collector configuration can be read"""
        try:
            self.orchestrator.get_otel_collector_probabilistic_sampling_values()
        except OxnException as e:
            self.messages.append(str(e.message))
            return False
        return True

    def inject(self) -> None:
        self.initial_sampling_percentage, self.initial_hash_seed = (
            self.orchestrator.get_otel_collector_probabilistic_sampling_values()
        )
        self.orchestrator.set_otel_collector_probabilistic_sampling_values(
            sampling_percentage=self.params.sampling_percentage, hash_seed=self.params.hash_seed
        )
        logger.info(
            f"Set otel collectors probabilistic sampling rate {self.initial_sampling_percentage} -> {self.params.sampling_percentage} and hash seed {self.initial_hash_seed} -> {self.params.hash_seed}"
        )

    def clean(self) -> None:
        # The sampling rate stays in place, resetting it would restart the collector again. To reset it:
        # self.orchestrator.set_otel_collector_probabilistic_sampling_values(
        #     sampling_percentage=self.initial_sampling_percentage, hash_seed=self.initial_hash_seed
        # )
        return
