"""
Purpose: Implements various treatments to be applied during experiments.
Functionality: Defines treatment classes that simulate different fault conditions or changes to the services under test.
Connection: Loaded by the Runner to apply treatments during an experiment.

Treatment implementations"""
from html.entities import name2codepoint
import logging
from os import name
import os.path
import time
import re
import trace
from typing import List, Optional, cast
import traceback

from kubernetes.client.models.v1_deployment import V1Deployment

from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator


from oxn.common.errors import OrchestratorException, OxnException, OrchestratorResourceNotFoundException
from oxn.common.utils import (
    time_string_to_seconds,
    validate_time_string,
    time_string_format_regex,
    to_milliseconds,
)
from oxn.models.treatment import Treatment

logger = logging.getLogger(__name__)


class EmptyTreatment(Treatment):
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
            if key in {"duration", } and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(
                        f"Parameter {key} has to match {time_string_format_regex}"
                    )
                    bools.append(False)
        return all(bools)

    def inject(self) -> None:
        sleep_duration_seconds = self.config.get("duration_seconds")
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

    def is_runtime(self):
        return True
    
    def _validate_orchestrator(self) -> bool:
        return True


class EmptyKubernetesTreatment(Treatment):
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
            if key in {"duration", } and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(
                        f"Parameter {key} has to match {time_string_format_regex}"
                    )
                    bools.append(False)
        return all(bools)

    def inject(self) -> None:
        sleep_duration_seconds = self.config.get("duration_seconds")
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

    def is_runtime(self):
        return True
    
    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True


class KubernetesApplySecurityContextTreatment(Treatment):
    """
    Treatment to escalate the privileges of a service account in a Kubernetes cluster
    """

    def clean(self) -> None:
        return
        super().clean()
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        
        assert namespace
        assert label_selector
        assert label
        assert self.config.get("capabilities")
        assert self.config.get("capabilities").get("add")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        # capabilities should now be the opisite of what was applied in inject (e.g. inject was { add: ["NET_ADMIN"] } so clean should be { remove: ["NET_ADMIN"] })
        capabilities = {"add": []}
        
        error_code, error = self.orchestrator.apply_security_context_to_deployment(
            namespace=namespace,
            label_selector=label_selector,
            label=label,
            capabilities=capabilities
        )
        
        logger.info(f"Applied security context to deployment in {namespace} with {label_selector}={label} with result {error_code}: {error}")

    def _transform_params(self) -> None:
        pass
    
    def _validate_params(self) -> bool:
        bools = []
        for key, value in self.params().items():
            if key in {"capabilities", "namespace", "label_selector", "label"} and key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(
                        f"Parameter {key} has to match {time_string_format_regex}"
                    )
                    bools.append(False)
        return all(bools)

    def inject(self) -> None:
        super().inject()
        capabilities = self.config.get("capabilities")
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        
        assert namespace
        assert label_selector
        assert label
        assert capabilities and capabilities.get("add")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        error_code, error = self.orchestrator.apply_security_context_to_deployment(
            namespace=namespace,
            label_selector=label_selector,
            label=label,
            capabilities=capabilities
        )
        logger.info(f"Applied security context to deployment in {namespace} with {label_selector}={label} with result {error_code}: {error}")
        # TODO: check if the deployment was actually updated and if so, wait for the deployment to be ready

    def params(self) -> dict:
        return {
            "capabilities": dict,
            "namespace": str,
            "label_selector": str,
            "label": str,
        }

    def preconditions(self) -> bool:
        return True

    @property
    def action(self):
        return "security_context_kubernetes"

    def is_runtime(self):
        return False
    
    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True




"""
    An Article on Add Java Agents to Existing Kubernetes and Helm Applications Instantly
    https://www.cncf.io/blog/2021/03/24/add-java-agents-to-existing-kubernetes-and-helm-applications-instantly/
    here with better format: https://www.rookout.com/blog/add-java-agents-to-existing-kubernetes-and-helm-applications-instantly/


    Regarding Maria, this treatment seems to be not working as expected and therefore has not to be used in the experiments for the first kubernetes experiments.
"""
class KubernetesCorruptPacketTreatment(Treatment):
    def action(self):
        return "kubernetes_corrupt"

    def preconditions(self) -> bool:
        super().preconditions()
        #service = self.config.get("service_name")
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        try:
            assert namespace
            assert label_selector
            assert label
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            try:
                response = self.orchestrator.patch_deployment_to_include_steering_sidecar_container(deployment=deployment)
                assert response

                if not response:
                    self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container")
                    return False
            except Exception as e:
                self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}")
                return False
        except Exception as e:
            self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}")
            return False
        return True
        

    def inject(self) -> None:
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        duration = self.config.get("duration_seconds")
        percentage = self.config.get("corrupt_percentage")
        correlation = self.config.get("corrupt_correlation") or "0%"

        assert duration
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)
       
        assert deployment
        
        result = self.orchestrator.orchestrate.set_network_corruption(deployment, interface, percentage, correlation)
        
        
        if not result:
            logger.error(
                f"Failed to inject packet loss into pods in {namespace} with {label_selector}={label}."
            )
            return
        logger.info(
            f"Injected packet loss into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
        )
        time.sleep(duration)
        

        logger.info(
            f"Injected packet corruption into deployment {deployment.metadata.name}. Waiting for {duration}s."
        )
        time.sleep(duration)

    def clean(self) -> None:
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)
        assert deployment
        result = self.orchestrator.orchestrate.remove_network_corruption(deployment, interface)
        if not result:
            logger.error(
                f"Failed to remove packet loss from pods in {namespace} with {label_selector}={label}."
            )
            return
        logger.info(
            f"Removed packet loss from pods in {namespace} with {label_selector}={label}."
        )
        
    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "interface": str,
            "duration": str,
            "corrupt_percentage": str,
            "corrupt_correlation": Optional[str],
        }
        
    def _validate_params(self) -> bool:
        bools = []
        for key, value in self.params().items():
            # required params
            if (
                    key in {"namespace", "label_selector", "label", "duration", "interface", "corrupt_percentage"}
                    and key not in self.config
            ):
                self.messages.append(f"Parameter {key} has to be supplied")
                bools.append(False)
            # supplied params have correct type
            if key in self.config and not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key, value in self.config.items():
            if key == "duration":
                if not validate_time_string(value):
                    self.messages.append(
                        f"Parameter {key} has to match {time_string_format_regex}"
                    )
                    bools.append(False)
            if key in {"corrupt_percentage", "corrupt_correlation"}:
                format_regex = r"^[1-9][0-9]?\%$|^100\%$"
                if not bool(re.match(format_regex, value)):
                    self.messages.append(f"Parameter {key} has to match {format_regex}")
                    bools.append(False)
        return all(bools)
    
    def _transform_params(self) -> None:
        relative_time_string = self.config.get("duration")
        relative_time_seconds = time_string_to_seconds(relative_time_string)
        self.config["duration_seconds"] = relative_time_seconds
        
    def is_runtime(self) -> bool:
        return True
    
    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])
    
    

class KubernetesMetricsExportIntervalTreatment(Treatment):
    """
    Modify the OTEL_METRICS_EXPORT interval for a given container

    check rate(otelcol_exporter_sent_metric_points[30s]) to validate the change

    config:
        namespace: system-under-evaluation,
        label_selector: app.kubernetes.io/component,
        label: recommendationservice,
        interval: 1s,
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.init_env_value = None
        self.env_name = "OTEL_METRIC_EXPORT_INTERVAL"
        
    def action(self):
        return "kubernetes_otel_metrics_interval"

    def preconditions(self) -> bool:
        super().preconditions()
        return True

    def inject(self) -> None:
        self.namespace = self.config.get("namespace")
        self.label_selector = self.config.get("label_selector")
        self.label = self.config.get("label")
        self.interval_ms = self.config.get("interval_ms")

        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)
        
        deployment_environment_variables = self.orchestrator.get_deployment_env_parameters(
            deployment=self.deployment
        )
        
        # get self.env_name from the deployments environment variables
        for env_var in deployment_environment_variables:
            if env_var.name == self.env_name:
                self.init_env_value = env_var.value
                break 

        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)
        result = self.orchestrator.set_deployment_env_parameter(
            deployment=self.deployment,
            environment_variable_name=self.env_name,
            environment_variable_value=str(int(self.interval_ms)),
        )
        
        logger.info(f"Environment variable '{self.env_name} set to '{self.interval_ms}'ms for the deployment '{self.deployment.metadata.name}'.")

        time.sleep(3)

        for x in range(0, 10):
            if self.orchestrator.is_deployment_ready(self.deployment):
                break
            logger.info(f"Waiting for deployment {self.deployment.metadata.name} to be ready")
            time.sleep(2)


    def clean(self) -> None:
        if self.init_env_value is None:
            return
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        # update the deployment as otherwise there will be an error because the deployment is outdated
        """ 
        TODO: uncomment this code before commit!
        self.deployment = self.orchestrator.get_deployment(self.namespace, self.label_selector, self.label)
        result = self.orchestrator.set_deployment_env_parameter(
            deployment=self.deployment,
            environment_variable_name=self.env_name,
            environment_variable_value=self.init_env_value,
        )
        logger.info(f"Environment variable '{self.env_name} reset for deployment '{self.deployment.metadata.name}' to initial value.") """

    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "interval": str,
        }

    def _validate_params(self) -> bool:
        for key, value in self.params().items():
            if key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied")
            if not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {str(value)}")
        for key in self.config.items():
            if key == "interval" and not validate_time_string(self.config[key]):
                self.messages.append(
                    f"Value for parameter {key} has to match {time_string_format_regex} for {self.treatment_type}"
                )
        return not self.messages

    def _transform_params(self) -> None:
        """Convert the provided time string into milliseconds"""
        interval_s = time_string_to_seconds(self.config["interval"])
        interval_ms = to_milliseconds(interval_s)
        self.config["interval_ms"] = interval_ms

    def is_runtime(self) -> bool:
        return False
    
    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])


class KubernetesProbabilisticHeadSamplingTreatment(Treatment):
        
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
            configmap = self.orchestrator.kube_client.read_namespaced_config_map(name=configmap_name, namespace="system-under-evaluation")
        except Exception as e:
            raise OrchestratorException(
                message=f"Error while reading ConfigMap {configmap_name} in namespace system-under-evaluation: {e.body}",
                explanation=str(e),
            )

        self.deployment = self.orchestrator.get_deployment("system-under-evaluation", "app.kubernetes.io/name", "opentelemetry-collector")

        if not configmap:
            self.messages.append(f"ConfigMap {configmap_name} not found in namespace system-under-evaluation")
            return False
        
        if self.deployment is None:
            self.messages.append(f"Deployment otelcol not found in namespace system-under-evaluation")
            return False
        

        return True

    def inject(self) -> None:
        assert isinstance(self.config.get("sampling_percentage"), (int, float))
        assert self.config.get("hash_seed")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        self.deployment = self.orchestrator.get_deployment("system-under-evaluation", "app.kubernetes.io/name", "opentelemetry-collector")
        
        self.initial_sampling_percentage, self.initial_hash_seed = self.orchestrator.get_otel_collector_probabilistic_sampling_values()
        self.orchestrator.set_otel_collector_probabilistic_sampling_values(sampling_percentage=self.config.get("sampling_percentage"), hash_seed=self.config.get("hash_seed"))
        logger.info(f"Set otel collectors probabilistic sampling rate {self.initial_sampling_percentage} -> {self.config.get('sampling_percentage')} and hash seed {self.initial_hash_seed} -> {self.config.get('hash_seed')}")


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
                self.messages.append(
                    f"Parameter {key} has to be of type {val} for {self.treatment_type}"
                )
        for key, value in self.config.items():
            if key == "sampling_percentage" and not (0 <= self.config[key] <= 100):
                self.messages.append(
                    f"Parameter {key} has to be between 0 and 100 for {self.treatment_type}"
                )
            if key == "sampling_percentage" and self.config[key] > 20:
               logger.warning(f"Sampling percentage is set to {self.config[key]}. High sampling rates can lead to high costs and performance issues and crashes.")
        return not self.messages

    def _transform_params(self) -> None:
       pass

    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])
    
    @property
    def action(self):
        return "kube_probl"

    def is_runtime(self) -> bool:
        return False


class KubernetesNetworkDelayTreatment(Treatment):
    """Inject network delay into a service"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = self.orchestrator

    action = "delay"

    def is_runtime(self) -> bool:
        return True

    def _validate_params(self) -> bool:
        for key, val in self.params().items():
            # required params
            if (
                    key in {"namespace", "label_selector", "label", "interface", "duration", "delay_time"}
                    and key not in self.config
            ):
                self.messages.append(
                    f"Parameter {key} has to be supplied for {self.treatment_type}"
                )
            # supplied params have correct type
            if key in self.config and not isinstance(self.config[key], val):
                self.messages.append(
                    f"Parameter {key} has to be of type {val.__class__.__name__} for {self.treatment_type}"
                )
        for key, value in self.config.items():
            if key in {"duration", "delay_time", "delay_jitter"}:
                if not validate_time_string(value):
                    self.messages.append(
                        f"Value for parameter {key} has to match {time_string_format_regex} for {self.treatment_type}"
                    )
            if key == "delay_correlation":
                format_regex = r"\d+\%"
                if not bool(re.match(format_regex, value)):
                    self.messages.append(
                        f"Value for parameter {key} has to match {format_regex} for {self.treatment_type}"
                    )
            if key == "distribution":
                distribution_set = {"uniform", "pareto", "normal", "paretonormal"}
                if key not in distribution_set:
                    self.messages.append(
                        f"Value for parameter {key} has to be one of {distribution_set} for {self.treatment_type}"
                    )
        return not self.messages

    def _transform_params(self) -> None:
        # correctly formatted params can be passed to tc directly as it can handle values + units
        # we need only transform the duration into seconds for the time.sleep call
        relative_time_string = self.config.get("duration")
        relative_time_seconds = time_string_to_seconds(relative_time_string)
        self.config["duration_seconds"] = relative_time_seconds

    def params(self) -> dict:
        return {
            "interface": str,
            "duration": str,
            "delay_time": str,
            "delay_jitter": Optional[str],
            "delay_correlation": Optional[str],
            "delay_distribution": Optional[str],
        }

    def preconditions(self) -> bool:
        super().preconditions()
        """Check if the service has tc installed"""
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        assert namespace
        assert label_selector
        assert label

        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        try:
            response = self.orchestrator.patch_deployment_to_include_steering_sidecar_container(deployment=deployment)
            assert response

            if not response:
                self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container")
                return False
        except Exception as e:
            self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}")
            return False
        
        return True

    def inject(self) -> None:
        super().inject()
        # required params
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        delay_time = self.config.get("delay_time")
        duration = self.config.get("duration_seconds")
        # optional params: use default values so we dont need to construct multiple commands
        jitter = self.config.get("delay_jitter", "0ms")
        correlation = self.config.get("delay_correlation", "0%")
        command = f"tc qdisc add dev {interface} root netem delay {delay_time} {jitter} {correlation}"
        try:
            assert namespace
            assert label_selector
            assert label
            assert duration
            assert isinstance(self.orchestrator, KubernetesOrchestrator)

            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            result = self.orchestrator.set_network_delay(deployment=deployment, interface=interface, delay_time=delay_time, jitter=jitter, correlation=correlation)
            
            if not result:
                logger.error(
                    f"Failed to inject delay into pods in {namespace} with {label_selector}={label}."
                )
                return
            logger.info(
                f"Injected delay into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
            )
            time.sleep(duration)
        except Exception as e:
            logger.error(
                f"Failed to inject delay into pods in {namespace} with {label_selector}={label}: {e}"
            )

    def clean(self) -> None:
        super().clean()
        interface = self.config.get("interface") or "eth0"
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        assert namespace
        assert label_selector
        assert label
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        result = self.orchestrator.remove_network_delay(deployment=deployment, interface=interface)
        
        logger.info(f"Cleaned delay treatment from pods in {namespace} with {label_selector}={label}")
        #self.client.close()
            
    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True

class KubernetesNetworkPacketLossTreatment(Treatment):
    """
    Inject network errors into a service to induce packet loss
    
    To high values of loss_percentage can provoke a cascading effect and lead to nearly 100% packet loss
    To low values of loss_percentage can lead to no effect at all or a small increas in latency
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = self.orchestrator

    action = "kubernetes_loss"

    def is_runtime(self) -> bool:
        return True

    def _validate_params(self) -> bool:
        for key, val in self.params().items():
            # required params
            if (
                    key in {"namespace", "label_selector", "label", "interface", "duration", "loss_percentage"}
                    and key not in self.config
            ):
                self.messages.append(
                    f"Parameter {key} has to be supplied for {self.treatment_type}"
                )
            # supplied params have correct type
            if key in self.config and not isinstance(self.config[key], val):
                self.messages.append(
                    f"Parameter {key} has to be of type {val.__class__.__name__} for {self.treatment_type}"
                )
        for key, value in self.config.items():
            if key in {"duration"}:
                if not validate_time_string(value):
                    self.messages.append(
                        f"Value for parameter {key} has to match {time_string_format_regex} for {self.treatment_type}"
                    )
        return not self.messages

    def _transform_params(self) -> None:
        # correctly formatted params can be passed to tc directly as it can handle values + units
        # we need only transform the duration into seconds for the time.sleep call
        relative_time_string = self.config.get("duration")
        relative_time_seconds = time_string_to_seconds(relative_time_string)
        self.config["duration_seconds"] = relative_time_seconds

    def params(self) -> dict:
        return {
            "interface": str,
            "duration": str,
            "loss_percentage": float,
        }

    def preconditions(self) -> bool:
        super().preconditions()
        """Check if the service has tc installed"""
        #service = self.config.get("service_name")
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        try:
            assert namespace
            assert label_selector
            assert label
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            try:
                response = self.orchestrator.patch_deployment_to_include_steering_sidecar_container(deployment=deployment)
                assert response

                if not response:
                    self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container")
                    return False
            except Exception as e:
                self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}")
                return False
        except Exception as e:
            self.messages.append(f"Failed to patch deployment {deployment.metadata.name} in namespace {namespace} with steering sidecar container: {e}")
            return False
        return True

    def inject(self) -> None:
        super().inject()
        # required params
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        interface = self.config.get("interface")
        duration = self.config.get("duration_seconds")
        loss_percentage = self.config.get("loss_percentage")
       
        assert namespace
        assert label_selector
        assert label
        assert duration
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

        assert deployment

        result = self.orchestrator.set_network_loss(deployment=deployment, interface=interface, loss=loss_percentage)
        
        if not result:
            logger.error(
                f"Failed to inject packet loss into pods in {namespace} with {label_selector}={label}."
            )
            return
        logger.info(
            f"Injected packet loss into pods in {namespace} with {label_selector}={label}. Waiting for {duration}s."
        )
        time.sleep(duration)

    def clean(self) -> None:
        super().clean()
        interface = self.config.get("interface") or "eth0"
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        try:
            assert namespace
            assert label_selector
            assert label
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            
            deployment = self.orchestrator.get_deployment(namespace, label_selector, label)

            assert deployment

            result = self.orchestrator.remove_network_loss(deployment=deployment, interface=interface)

            if not result:
                logger.error(f"Failed to clean packet loss from pods in {namespace} with {label_selector}={label}.")
                return
            
            logger.info(f"Cleaned packet loss treatment from pods in {namespace} with {label_selector}={label}")
            #self.client.close()
        except Exception as e:
            logger.error(f"Cannot clean packet loss treatment from pods in {namespace} with {label_selector}={label}: {e}")
            logger.error(f"State for pods in {namespace} with {label_selector}={label} might be polluted now")
            
    def _validate_orchestrator(self) -> bool:
        if self.orchestrator.get_orchestrator_type() != "kubernetes":
            self.messages.append(f"{self.name} treatment is only supported for Kubernetes orchestrators")
            return False
        return True
    

class DeploymentScaleTreatment(Treatment):
    """
    Will scale a deployment to 0 replicas and back to the original number of replicas.
    """
    
    action = "scale_deployment"


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.replicas_before = 0
        self.deployment = None



    def preconditions(self) -> bool:
        """Check if the deployment exists"""
        super().preconditions()
        return True
        
        

    def inject(self) -> None:
        super().inject()
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        scale_to = self.config.get("scale_to")
        assert scale_to is not None and scale_to >= 0 
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.deployment = KubernetesOrchestrator.get_deployment(self.orchestrator, namespace, label_selector, label)
            if self.deployment is None:
                self.messages.append(f"Deployment with {label_selector}={label} not found in namespace {namespace}")
                return
        except OrchestratorException as e:
            self.messages.append(e.message)
            return 
        
        assert self.deployment.spec
        assert self.deployment.metadata
        assert self.deployment.metadata.name

        self.replicas_before = self.deployment.spec.replicas
        response = KubernetesOrchestrator.scale_deployment(self.orchestrator, self.deployment, scale_to)
        if response is None:
            self.messages.append(f"Failed to scale deployment {self.deployment.metadata.name} to {scale_to}")
            return
        # TODO: Wait until scaling is done
        logger.info(f"Deployment {self.deployment.metadata.name} scaled to {scale_to}")

    def clean(self) -> None:
        """
        Scale the deployment back to the original number of replicas.

        We have to fetch the deployment again as otherwise there will be an error form the kubernetes API because the deployment object is not up to date.
        """
        super().clean()
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        try:
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.deployment = KubernetesOrchestrator.get_deployment(self.orchestrator, namespace, label_selector, label)
            if self.deployment is None:
                self.messages.append(f"Deployment with {label_selector}={label} not found in namespace {namespace}")
                return
        except OrchestratorException as e:
            self.messages.append(e.message)
            return 
        assert self.deployment.metadata
        assert self.deployment.metadata.name
        response = KubernetesOrchestrator.scale_deployment(self.orchestrator, self.deployment, self.replicas_before)
        if response is None:
            self.messages.append(f"Failed to scale deployment {self.deployment.metadata.name} to {self.replicas_before}")
            return
        logger.info(f"Deployment {self.deployment.metadata.name} scaled to {self.replicas_before}")

    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "scale_to": int,
        }

    def _validate_params(self) -> bool:
        """ 
        Check if all required parameters are supplied and have the correct type.        
        """

        for key, value in self.params().items():
            if key not in self.config:
                self.messages.append(f"Parameter {key} has to be supplied for {self.treatment_type}")
            if not isinstance(self.config[key], value):
                self.messages.append(f"Parameter {key} has to be of type {value} for {self.treatment_type}")

        return not self.messages
        

    def _transform_params(self) -> None:
        pass

    def is_runtime(self) -> bool:
        return False

    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])


class KubernetesKillTreatment(Treatment):
    """
    Kill a Kubernetes Pod.
    """

    action = "kubernetes_kill"

    def preconditions(self) -> bool:
        """Check if the kubernetes pod is running"""
        super().preconditions()
        namespace = self.config.get("namespace")
        label_selector = self.config.get("label_selector")
        label = self.config.get("label")
        amount_to_kill = self.config.get("amount_to_kill")
        try:
            assert namespace
            assert label_selector
            assert label
            assert amount_to_kill
            assert isinstance(self.orchestrator, KubernetesOrchestrator)
            self.pods = KubernetesOrchestrator.get_pods(self.orchestrator, namespace, label_selector, label)
            if self.pods is None:
                self.messages.append(f"Pod with {label_selector}={label} not found in namespace {namespace}")
                return False
            
            if len(self.pods) < amount_to_kill:
                self.messages.append(f"Amount to kill is higher than the amount of pods matching the label selector. Amount to kill: {amount_to_kill}, amount of pods found for label selector: {len(self.pods)}")
                return False
                
            for pod in self.pods:
                if pod.status and pod.status.phase != "Running":
                    self.messages.append(f"At least one Pod ({pod.metadata.name}) is not running ({pod.status.phase})")
                    return False
        
        except OrchestratorException as e:
            self.messages.append(e.message)
            return False
        
        return True

    def inject(self) -> None:
        assert self.pods
        assert self.orchestrator
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        if not self.pods:
            logger.error("No pods found to kill")
            return
        
        amount_to_kill = self.config.get("amount_to_kill")
        pods_to_kill = self.pods[:amount_to_kill]
        for pod in pods_to_kill:
            KubernetesOrchestrator.kill_pod(self.orchestrator, pod)
            
        # TODO: scale down deployment of the pods?
        
        logger.debug(f"Killed {amount_to_kill} pods.")

    def clean(self) -> None:
        # TODO: Wait untill als pods are running again?
        super().clean()

    def params(self) -> dict:
        return {
            "namespace": str,
            "label_selector": str,
            "label": str,
            "amount_to_kill": int,
        }

    def _validate_params(self) -> bool:
        for key, value in self.params().items():
            if key == "namespace" and key not in self.config:
                self.messages.append(
                    f"Parameter {key} has to be supplied for {self.treatment_type}"
                )
            if key == "label_selector" and key not in self.config:
                self.messages.append(
                    f"Parameter {key} has to be supplied for {self.treatment_type}"
                )
            if key == "label" and key not in self.config:
                self.messages.append(
                    f"Parameter {key} has to be supplied for {self.treatment_type}"
                )
            if key == "amount_to_kill" and key not in self.config:
                self.messages.append(
                    f"Parameter {key} has to be supplied for {self.treatment_type}"
                )
        return not self.messages
    
    def _transform_params(self) -> None:
        return super()._transform_params()

    def is_runtime(self) -> bool:
        return True
    
    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])


class PacketReorderTreatment(Treatment):
    """
    Reorder packets. This can be used to simulate different cache locality effects.
    This is an example of a non-destructive treatment incompatible with the chaos engineering approach.
    Rather, this could be used to improve upon the system.
    Confer https://www.usenix.org/conference/nsdi22/presentation/ghasemirahni
    """

    # TODO: implement packet reordering


class SlotTreatment(Treatment):
    """Defer the delivery of accumulated packets to within a slot.
    Each slot is configurable with a minimum delay, number of bytes delivered per slot and
    number of delivered packets per slot.

    This treatment can be used to simulate bursty traffic, i.e. network congestion effects.
    """

    # TODO: implement slot treatment


class KubernetesPrometheusIntervalTreatment(Treatment):
    """
    Treatment to change the global scrape interval of a Prometheus instance.

    """

    def preconditions(self) -> bool:
        """Check that the config exists at the specified location and that Prometheus is running"""
        return True

    def inject(self) -> None:
        assert self.config.get("interval")
        assert self.config.get("evaluation_interval")
        assert self.config.get("scrape_timeout")
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        
        self.deployment = self.orchestrator.get_deployment("system-under-evaluation", "app.kubernetes.io/name", "prometheus")
        
        self.initial_interval, self.initial_evaluation_interval, self.inital_scrape_timeout = self.orchestrator.get_prometheus_scrape_values()
        self.orchestrator.set_prometheus_scrape_values(scrape_interval=self.config.get("interval"), evaluation_interval=self.config.get("evaluation_interval"), scrape_timeout=self.config.get("scrape_timeout"))
        logger.info(f"Set prometheus scrape interval to {self.config.get('interval')}, evaluation interval to {self.config.get('evaluation_interval')} and scrape timeout to {self.config.get('scrape_timeout')}")

        self.orchestrator.restart_pods_of_deployment(self.deployment)


    def clean(self) -> None:
        return
        # if we clean up the changes to prometheus, the pods have to be restarted. The prometheus data is currently not persistent, so we would loose the benchmark data.
        
        assert isinstance(self.orchestrator, KubernetesOrchestrator)
        self.orchestrator.set_prometheus_scrape_values(scrape_interval=self.initial_interval, evaluation_interval=self.initial_evaluation_interval, scrape_timeout=self.inital_scrape_timeout)
        logger.info(f"Set prometheus scrape interval back to {self.initial_interval}, evaluation interval back to {self.initial_evaluation_interval} and scrape timeout back to {self.inital_scrape_timeout}")

        self.deployment = self.orchestrator.get_deployment("system-under-evaluation", "app.kubernetes.io/name", "prometheus")
        self.orchestrator.restart_pods_of_deployment(self.deployment)


    def params(self) -> dict:
        return {
            "interval": str,
            "evaluation_interval": str,
            "scrape_timeout": str,
        }

    def _validate_params(self) -> bool:
        for key, val in self.params().items():
            if key in self.config and not isinstance(self.config[key], val):
                self.messages.append(
                    f"Parameter {key} has to be of type {val} for {self.treatment_type}"
                )
        for key, value in self.config.items():
            prometheus_regex = (
                r"((([0-9]+)y)?(([0-9]+)w)?(([0-9]+)d)?(([0-9]+)h)?(([0-9]+)m)?((["
                r"0-9]+)s)?(([0-9]+)ms)?|0)"
            )
            if key == "interval" and not bool(re.match(prometheus_regex, value)):
                self.messages.append(
                    f"Parameter {key} has to match {prometheus_regex} for {self.treatment_type}"
                )
            if key == "evaluation_interval" and not bool(re.match(prometheus_regex, value)):
                self.messages.append(
                    f"Parameter {key} has to match {prometheus_regex} for {self.treatment_type}"
                )
            if key == "scrape_timeout" and not bool(re.match(prometheus_regex, value)):
                self.messages.append(
                    f"Parameter {key} has to match {prometheus_regex} for {self.treatment_type}"
                )
        return not self.messages

    def _transform_params(self) -> None:
       pass

    def _validate_orchestrator(self) -> bool:
        return super()._validate_orchestrator(["kubernetes"])
    
    @property
    def action(self):
        return "sampling"

    def is_runtime(self) -> bool:
        return False
