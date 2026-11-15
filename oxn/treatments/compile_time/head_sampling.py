"""Change the probabilistic head sampling rate of the OpenTelemetry collector"""

import logging

from kubernetes.client.exceptions import ApiException
from pydantic import Field, field_validator

from oxn.common.errors import OrchestratorException
from oxn.models.treatment import CompileTimeTreatment
from oxn.models.treatment_params import TreatmentParams
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

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


class KubernetesProbabilisticHeadSamplingTreatment(CompileTimeTreatment[HeadSamplingParams]):
    """
    Treatment to change the global sampling rate for head-based trace sampling in the OpenTelemetry collector

    use "increase(otelcol_processor_probabilistic_sampler_count_traces_sampled[1m])" in prometheus to see the change between sampled:true and sampled:false when changing the sampling percentage

    otel documentation: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/probabilisticsamplerprocessor

    """

    action = "kube_probl"
    Params = HeadSamplingParams

    def preconditions(self) -> bool:
        """Check that the config exists at the specified location and that Prometheus is running"""
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        configmap_name = "otel-collector"

        try:
            configmap = self.orchestrator.kube_client.read_namespaced_config_map(
                name=configmap_name, namespace="system-under-evaluation"
            )
        except ApiException as e:
            raise OrchestratorException(
                message=f"Error while reading ConfigMap {configmap_name} in namespace system-under-evaluation: {e.body}",
                explanation=str(e),
            )

        self.deployment = self.orchestrator.get_deployment(
            "system-under-evaluation", "app.kubernetes.io/name", "opentelemetry-collector"
        )

        if not configmap:
            self.messages.append(f"ConfigMap {configmap_name} not found in namespace system-under-evaluation")
            return False

        if self.deployment is None:
            self.messages.append("Deployment otelcol not found in namespace system-under-evaluation")
            return False

        return True

    def inject(self) -> None:
        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        self.deployment = self.orchestrator.get_deployment(
            "system-under-evaluation", "app.kubernetes.io/name", "opentelemetry-collector"
        )

        self.initial_sampling_percentage, self.initial_hash_seed = (
            self.orchestrator.get_otel_collector_probabilistic_sampling_values()
        )
        self.orchestrator.set_otel_collector_probabilistic_sampling_values(
            sampling_percentage=self.params.sampling_percentage, hash_seed=self.params.hash_seed
        )
        logger.info(
            f"Set otel collectors probabilistic sampling rate {self.initial_sampling_percentage} -> {self.params.sampling_percentage} and hash seed {self.initial_hash_seed} -> {self.params.hash_seed}"
        )

        # TODO: it seams as there might be a way to reload config maps without restarting the pods in some cases. This should be investigated (https://kubernetes.io/docs/concepts/configuration/configmap/#mounted-configmaps-are-updated-automatically)
        self.orchestrator.restart_pods_of_deployment(self.deployment)

    def clean(self) -> None:
        assert self.initial_sampling_percentage
        assert self.initial_hash_seed
        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        """  self.orchestrator.set_otel_collector_probabilistic_sampling_values(sampling_percentage=self.initial_sampling_percentage, hash_seed=self.initial_hash_seed)
        logger.info(f"Reset otel collectors probabilistic sampling rate  {self.params.sampling_percentage} -> {self.initial_sampling_percentage} and hash seed to {self.params.hash_seed} -> {self.initial_hash_seed}")

         # TODO: it seams as there might be a way to reload config maps without restarting the pods in some cases. This should be investigated (https://kubernetes.io/docs/concepts/configuration/configmap/#mounted-configmaps-are-updated-automatically)
        self.orchestrator.restart_pods_of_deployment(self.deployment) """

        return

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])
