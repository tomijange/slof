"""Compile-time treatments, see oxn.models.treatment.CompileTimeTreatment"""

from oxn.treatments.compile_time.deployment_scale import DeploymentScaleTreatment
from oxn.treatments.compile_time.head_sampling import KubernetesProbabilisticHeadSamplingTreatment
from oxn.treatments.compile_time.metrics_export_interval import KubernetesMetricsExportIntervalTreatment
from oxn.treatments.compile_time.prometheus_interval import KubernetesPrometheusIntervalTreatment
from oxn.treatments.compile_time.security_context import KubernetesApplySecurityContextTreatment

__all__ = [
    "KubernetesApplySecurityContextTreatment",
    "KubernetesMetricsExportIntervalTreatment",
    "KubernetesProbabilisticHeadSamplingTreatment",
    "DeploymentScaleTreatment",
    "KubernetesPrometheusIntervalTreatment",
]
