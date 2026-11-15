"""Change the probabilistic head sampling rate of the OpenTelemetry collector"""

import logging

from kubernetes.client.exceptions import ApiException

from oxn.common.errors import OrchestratorException
from oxn.models.treatment import CompileTimeTreatment
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator

logger = logging.getLogger(__name__)


class KubernetesProbabilisticHeadSamplingTreatment(CompileTimeTreatment):
    """
    Treatment to change the global sampling rate for head-based trace sampling in the OpenTelemetry collector

    use "increase(otelcol_processor_probabilistic_sampler_count_traces_sampled[1m])" in prometheus to see the change between sampled:true and sampled:false when changing the sampling percentage

    otel documentation: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/probabilisticsamplerprocessor

    """

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
        assert isinstance(self.config.get("sampling_percentage"), (int, float))
        assert self.config.get("hash_seed")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        self.deployment = self.orchestrator.get_deployment(
            "system-under-evaluation", "app.kubernetes.io/name", "opentelemetry-collector"
        )

        self.initial_sampling_percentage, self.initial_hash_seed = (
            self.orchestrator.get_otel_collector_probabilistic_sampling_values()
        )
        self.orchestrator.set_otel_collector_probabilistic_sampling_values(
            sampling_percentage=self.config.get("sampling_percentage"), hash_seed=self.config.get("hash_seed")
        )
        logger.info(
            f"Set otel collectors probabilistic sampling rate {self.initial_sampling_percentage} -> {self.config.get('sampling_percentage')} and hash seed {self.initial_hash_seed} -> {self.config.get('hash_seed')}"
        )

        # TODO: it seams as there might be a way to reload config maps without restarting the pods in some cases. This should be investigated (https://kubernetes.io/docs/concepts/configuration/configmap/#mounted-configmaps-are-updated-automatically)
        self.orchestrator.restart_pods_of_deployment(self.deployment)

    def clean(self) -> None:
        assert self.initial_sampling_percentage
        assert self.initial_hash_seed
        assert isinstance(self.orchestrator, KubernetesOrchestrator)

        """  self.orchestrator.set_otel_collector_probabilistic_sampling_values(sampling_percentage=self.initial_sampling_percentage, hash_seed=self.initial_hash_seed)
        logger.info(f"Reset otel collectors probabilistic sampling rate  {self.config.get('sampling_percentage')} -> {self.initial_sampling_percentage} and hash seed to {self.config.get('hash_seed')} -> {self.initial_hash_seed}")

         # TODO: it seams as there might be a way to reload config maps without restarting the pods in some cases. This should be investigated (https://kubernetes.io/docs/concepts/configuration/configmap/#mounted-configmaps-are-updated-automatically)
        self.orchestrator.restart_pods_of_deployment(self.deployment) """

        return

    def params(self) -> dict:
        return {
            "sampling_percentage": float,
            "hash_seed": int,
        }

    def _validate_params(self) -> bool:
        for key, val in self.params().items():
            if key in self.config and not isinstance(self.config[key], val):
                self.messages.append(f"Parameter {key} has to be of type {val} for {self.treatment_type}")
        for key, value in self.config.items():
            if key == "sampling_percentage" and not (0 <= self.config[key] <= 100):
                self.messages.append(f"Parameter {key} has to be between 0 and 100 for {self.treatment_type}")
            if key == "sampling_percentage" and self.config[key] > 20:
                logger.warning(
                    f"Sampling percentage is set to {self.config[key]}. High sampling rates can lead to high costs and performance issues and crashes."
                )
        return not self.messages

    def _transform_params(self) -> None:
        pass

    def _validate_orchestrator(self) -> bool:
        return self._orchestrator_is_one_of(["kubernetes"])

    @property
    def action(self):
        return "kube_probl"
