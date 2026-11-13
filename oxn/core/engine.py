""" 
Purpose: Core logic for executing experiments.
Functionality: Manages the orchestration, execution, and observation of experiments.
Connection: Central component that coordinates between treatments, load generation, and response observation.

 """

import logging
import time
from typing import Optional

import yaml

from oxn.core.runner import ExperimentRunner
from oxn.orchestration.docker_orchestration import DockerComposeOrchestrator
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
from oxn.reporting.report import Reporter
from oxn.reporting.store import write_dataframe
from oxn.loadgen.config_load_generator import ConfigLoadGenerator
from oxn.loadgen.file_load_generator import LocustFileLoadgenerator
from oxn.loadgen.locust_kubernetes import LocustKubernetesLoadgenerator
from oxn.common.utils import utc_timestamp
from oxn.core.validation import load_experiment_specification
from oxn.core.context import Context
from oxn.common.errors import OxnException, OrchestrationException
from oxn.models.experiment_spec import ExperimentSpec

logger = logging.getLogger(__name__)


class Engine:
    """
    Observability experiments engine

    This class encapsulates all behavior needed to execute observability experiments.
    """

    def __init__(self, configuration_path=None, report_path=None, treatment_file=None):
        assert configuration_path is not None, "Configuration path must be specified"
        self.config = configuration_path
        """The path to the configuration file for this engine"""
        self.spec: Optional[ExperimentSpec] = None
        """The loaded experiment specification"""
        self.report_path = report_path
        """The path to write the experiment report to"""
        assert report_path is not None, "Report path must be specified"
        self.reporter = Reporter(report_path=report_path)
        """A reference to a reporter instance"""
        self.context = Context(treatment_file_path=treatment_file)
        """A reference to a treatment context"""
        self.additional_treatments = self.context.load_treatment_file()
        """Additional treatments defined by the user"""
        self.orchestrator = None
        """A reference to an orchestrator instance"""
        self.generator = None
        """A reference to a load generator instance"""
        self.runner = None
        """A reference to a runner instance"""
        self.loadgen_running = False
        """Status of the load generator"""
        self.sue_running = False
        """Status of the sue"""

    def load_experiment_specification(self):
        """Read the experiment specification file and validate it syntactically"""
        self.spec = load_experiment_specification(self.config)
        logger.debug(f"Experiment specification {self.config} is valid")

    def run(
        self,
        runs=None,
        orchestration_timeout=None,
        randomize=False,
        accounting=False,
        keep_sue=False,
    ):
        """Run an experiment n times"""
        assert runs is not None, "Number of runs must be specified"
        logger.info(f"Running experiment {self.config} for {runs} times")
        for idx in range(runs):
            logger.info(f"Experiment run {idx + 1} of {runs}")
            run_start = time.monotonic()
            assert self.spec
            if self.spec.experiment.orchestrator == "docker-compose":
                self.orchestrator = DockerComposeOrchestrator(
                    experiment_config=self.spec,
                )
            else:
                self.orchestrator = KubernetesOrchestrator(
                    experiment_config=self.spec,
                )
            names = []
            """ (
                self.orchestrator.translate_compose_names(
                    self.orchestrator.sue_service_names
                )
                if accounting
                else []
            ) """
            self.runner = ExperimentRunner(
                config=self.spec,
                config_filename=self.config,
                additional_treatments=self.additional_treatments,
                random_treatment_order=randomize,
                accountant_names=names,
                orchestrator=self.orchestrator,
            )
            logger.info(f"Run id is {self.runner.short_id}")
            # Kubernetes treatments patch the running SUE, Docker Compose treatments change what gets built
            deploy_first = self.spec.experiment.orchestrator == "kubernetes"
            if not deploy_first:
                self.runner.execute_compile_time_treatments()
            try:
                self.orchestrator.orchestrate()
            except OxnException:
                if not deploy_first:
                    self.runner.clean_compile_time_treatments()
                if not keep_sue:
                    self.orchestrator.teardown()
                raise
            # from here on main() tears down the SUE if anything goes wrong
            self.sue_running = True
            if deploy_first:
                self.runner.execute_compile_time_treatments()
            if not self.orchestrator.ready(expected_services=None, timeout=orchestration_timeout):
                self.runner.clean_compile_time_treatments()
                raise OrchestrationException(
                    message="Error while building the sue",
                    explanation=f"Could not build the sue within {orchestration_timeout}",
                )
            logger.info(f"Started sue after {time.monotonic() - run_start:.0f}s")
            # resolves the address of the load target, so the SUE has to exist already
            self.generator = LocustKubernetesLoadgenerator(orchestrator=self.orchestrator, config=self.spec)
            for treatment in self.runner.treatments.values():
                logger.debug(f"Checking preconditions of treatment {treatment.name}")
                if not treatment.preconditions():
                    raise OxnException(
                        message=f"Error while checking preconditions for treatment {treatment.name} which is class {treatment.__class__}",
                        explanation="\n".join(treatment.messages),
                    )
            self.generator.start()
            logger.info("Started load generation")
            self.loadgen_running = True
            experiment_start = utc_timestamp()
            self.runner.experiment_start = experiment_start
            self.runner.observer.experiment_start = experiment_start
            self.runner.execute_runtime_treatments()
            self.runner.clean_compile_time_treatments()
            self.runner.experiment_end = utc_timestamp()
            self.runner.observer.experiment_end = self.runner.experiment_end
            self.runner.observe_response_variables()
            self.generator.stop()
            self.loadgen_running = False
            logger.info("Stopped load generation")
            for _, response in self.runner.observer.variables().items():
                if response.data is None:
                    logger.warning(f"Skipping {response.name}, no data was captured")
                    continue
                write_dataframe(
                    dataframe=response.data,
                    experiment_key=self.runner.config_filename,
                    run_key=self.runner.short_id,
                    response_key=response.name,
                )
                logger.info(f"Wrote {response.name} with {len(response.data)} rows to store")
                if self.report_path:
                    for _, treatment in self.runner.treatments.items():
                        self.reporter.gather_interaction(
                            experiment=self.runner,
                            treatment=treatment,
                            response=response,
                        )
                        logger.debug(
                            f"Gathered interaction data for {treatment} and {response}"
                        )
                    self.reporter.assemble_interaction_data(
                        run_key=self.runner.short_id
                    )
                    logger.debug("Assembled all interaction data")
                    if self.generator.env is not None:
                        self.reporter.add_loadgen_data(
                            runner=self.runner, request_stats=self.generator.env.stats
                        )
                    else:
                        self.reporter.add_loadgen_data_kubernetes_locust(self.generator, self.runner)
                    logger.debug("Added load generation data")
                    if accounting:
                        self.reporter.add_accountant_data(runner=self.runner)
                        logger.debug("Added accounting data")
            if not keep_sue:
                self.orchestrator.teardown()
                logger.info("Stopped sue")
            self.sue_running = False
            logger.info(f"Experiment run {idx + 1} of {runs} completed after {time.monotonic() - run_start:.0f}s")
        if self.report_path:
            self.reporter.dump_report_data()
