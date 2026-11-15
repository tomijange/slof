""" 
Purpose: Core logic for executing experiments.
Functionality: Manages the orchestration, execution, and observation of experiments.
Connection: Central component that coordinates between treatments, load generation, and response observation.

 """

import logging
import time
from enum import Enum
from typing import Optional

import yaml

from oxn.core.runner import ExperimentRunner
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


class Phase(Enum):
    """
    The step of an experiment run the engine is in

    main() reads the phase after the run ends or fails to decide what to clean up.
    """

    INITIALIZATION = "initialization"
    """Nothing is deployed yet"""
    ORCHESTRATION = "orchestration"
    """The SUE is being deployed"""
    PREPARATION = "preparation"
    """Compile-time treatments, readiness and precondition checks on the deployed SUE"""
    LOAD = "load"
    """The load generator is starting or running, runtime treatments run and responses are observed"""
    REPORTING = "reporting"
    """The load generator has stopped, responses are stored and reported"""
    TEARDOWN = "teardown"
    """The SUE is being removed"""
    COMPLETED = "completed"
    """The run is done, the SUE is removed unless --keep-sue is set"""

    @property
    def sue_deployed(self) -> bool:
        """Whether the SUE may be deployed, fully or in part, in this phase"""
        return self not in (Phase.INITIALIZATION, Phase.COMPLETED)

    @property
    def loadgen_running(self) -> bool:
        """Whether the load generator may be running in this phase"""
        return self is Phase.LOAD


class Engine:
    """
    Observability experiments engine

    This class encapsulates all behavior needed to execute observability experiments.
    """

    def __init__(self, configuration_path=None, report_path=None, treatment_file=None, keep_sue=False):
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
        self.phase = Phase.INITIALIZATION
        """The step of the current run, see Phase"""
        self.keep_sue = keep_sue
        """Whether teardown() leaves the SUE deployed"""

    def _enter(self, phase: Phase):
        logger.debug(f"Entering phase {phase.value}")
        self.phase = phase

    def load_experiment_specification(self):
        """Read the experiment specification file and validate it syntactically"""
        self.spec = load_experiment_specification(self.config)
        logger.debug(f"Experiment specification {self.config} is valid")

    def run(
        self,
        runs=None,
        orchestration_timeout=None,
        randomize=False,
    ):
        """Run an experiment n times"""
        assert runs is not None, "Number of runs must be specified"
        logger.info(f"Running experiment {self.config} for {runs} times")
        for idx in range(runs):
            logger.info(f"Experiment run {idx + 1} of {runs}")
            run_start = time.monotonic()
            assert self.spec
            self.orchestrator = KubernetesOrchestrator(
                experiment_config=self.spec,
            )
            self.runner = ExperimentRunner(
                config=self.spec,
                config_filename=self.config,
                additional_treatments=self.additional_treatments,
                random_treatment_order=randomize,
                orchestrator=self.orchestrator,
            )
            logger.info(f"Run id is {self.runner.short_id}")
            # from here on main() tears down the SUE if anything goes wrong, even a partial deploy
            self._enter(Phase.ORCHESTRATION)
            self.orchestrator.orchestrate()
            self._enter(Phase.PREPARATION)
            # compile-time treatments patch the deployed SUE, so they run after orchestration
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
            # entered before start(), so main() also kills a generator that fails or is interrupted while starting
            self._enter(Phase.LOAD)
            self.generator.start()
            logger.info("Started load generation")
            experiment_start = utc_timestamp()
            self.runner.experiment_start = experiment_start
            self.runner.observer.experiment_start = experiment_start
            self.runner.execute_runtime_treatments()
            self.runner.clean_compile_time_treatments()
            self.runner.experiment_end = utc_timestamp()
            self.runner.observer.experiment_end = self.runner.experiment_end
            self.runner.observe_response_variables()
            self.generator.stop()
            self._enter(Phase.REPORTING)
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
            self.teardown()
            logger.info(f"Experiment run {idx + 1} of {runs} completed after {time.monotonic() - run_start:.0f}s")
        if self.report_path:
            self.reporter.dump_report_data()

    def teardown(self):
        """
        Clean up what the current phase left running

        Ends every run, and main() calls it after an error or ctrl-c. Kills the load generator if it may
        still run and removes the SUE if it may be deployed, unless keep_sue is set. If removing the SUE
        fails, the phase stays at teardown, so calling this again retries it.
        """
        if self.phase.loadgen_running:
            assert self.generator is not None
            self.generator.kill()
            logger.info("Shut down load generation")
        if self.phase.sue_deployed and not self.keep_sue:
            # TODO: clean up treatments here, they only go away with the SUE
            assert self.orchestrator is not None
            self._enter(Phase.TEARDOWN)
            self.orchestrator.teardown()
            logger.info("Shut down sue")
        self._enter(Phase.COMPLETED)
