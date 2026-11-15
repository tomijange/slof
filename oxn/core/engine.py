"""
Purpose: Core logic for executing experiments.
Functionality: Manages the orchestration, execution, and observation of experiments.
Connection: Central component that coordinates between treatments, load generation, and response observation.

"""

import logging
import random
import time
from enum import Enum
from typing import List, Optional, Sequence

from oxn.common.errors import OrchestrationException, OxnException
from oxn.common.log import log_exception
from oxn.common.utils import utc_timestamp
from oxn.core.context import Context
from oxn.core.runner import ExperimentRunner
from oxn.core.validation import ExperimentVariant, load_variants
from oxn.loadgen.locust_kubernetes import LocustKubernetesLoadgenerator
from oxn.models.experiment_spec import ExperimentSpec
from oxn.orchestration.kubernetes_orchestrator import KubernetesOrchestrator
from oxn.reporting.report import Reporter
from oxn.reporting.store import write_dataframe
from oxn.treatments.registry import TreatmentRegistry

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

    def __init__(
        self,
        configuration_path=None,
        report_path=None,
        treatment_file=None,
        keep_sue=False,
        only: Sequence[str] = (),
        fail_fast=False,
    ):
        assert configuration_path is not None, "Configuration path must be specified"
        self.config = configuration_path
        """The path to the configuration file for this engine"""
        self.only = list(only)
        """Selections like sampling=10.0 that pick the variants of the spec's matrix to run"""
        self.variants: List[ExperimentVariant] = []
        """The selected variants of the spec, a single one without levels for a spec without a matrix"""
        self.spec: Optional[ExperimentSpec] = None
        """The specification of the variant that runs now"""
        self.fail_fast = fail_fast
        """Whether a failed run stops all others. Otherwise it is torn down and the next run starts"""
        self.report_path = report_path
        """The path to write the experiment report to"""
        assert report_path is not None, "Report path must be specified"
        self.reporter = Reporter(report_path=report_path)
        """A reference to a reporter instance"""
        self.context = Context(treatment_file_path=treatment_file)
        """A reference to a treatment context"""
        self.treatment_registry = TreatmentRegistry(self.context.load_treatment_file())
        """The built-in treatments and those defined by the user"""
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
        """
        Read the experiment specification file, expand its matrix and validate the selected variants syntactically,
        including the treatment params
        """
        self.variants = load_variants(self.config, treatments=self.treatment_registry, only=self.only)
        if self.variants[0].variant.levels:
            logger.info(
                f"Experiment specification {self.config} is valid, running {len(self.variants)} variants: "
                + "; ".join(experiment.variant.id for experiment in self.variants)
            )
        else:
            logger.debug(f"Experiment specification {self.config} is valid")

    def schedule(self, runs: int, randomize_variants=False) -> List[ExperimentVariant]:
        """
        The order of all runs: every variant once per round, for runs rounds

        Interleaving the variants spreads drift of the cluster over all of them, instead of giving it to the
        variants that run last. With randomize_variants, each round runs the variants in a new random order.
        """
        order = []
        for _ in range(runs):
            variants = list(self.variants)
            if randomize_variants:
                random.shuffle(variants)
            order += variants
        return order

    def run(
        self,
        runs=None,
        orchestration_timeout: float = 60,
        randomize=False,
        randomize_variants=False,
    ):
        """
        Run every variant of the experiment n times

        A failed run is torn down and the next one starts, unless fail_fast is set. Then the exception is raised as
        is, and main() tears down what it left. Raises an OxnException that lists the failed runs at the end.
        """
        assert runs is not None, "Number of runs must be specified"
        assert self.variants, "Load the experiment specification first"
        schedule = self.schedule(runs, randomize_variants=randomize_variants)
        logger.info(f"Running experiment {self.config}: {len(self.variants)} variants x {runs} runs")
        failed = []
        for idx, experiment in enumerate(schedule):
            name = f"run {idx + 1} of {len(schedule)}"
            if experiment.variant.levels:
                name += f", variant {experiment.variant.id}"
            logger.info(f"Experiment {name}")
            run_start = time.monotonic()
            try:
                self._run_once(experiment, orchestration_timeout=orchestration_timeout, randomize=randomize)
            except OxnException as e:
                if self.fail_fast:
                    raise
                log_exception(logger, e)
                logger.error(f"Experiment {name} failed in phase {self.phase.value}, tearing it down")
                failed.append(name)
                # a failed teardown raises, and main() retries it instead of starting the next run on a broken SUE
                self.teardown()
            else:
                logger.info(f"Experiment {name} completed after {time.monotonic() - run_start:.0f}s")
            if self.report_path:
                # after every run, so an interrupted series keeps the report of the finished runs
                self.reporter.dump_report_data()
        if failed:
            raise OxnException(
                message=f"{len(failed)} of {len(schedule)} runs failed",
                explanation="; ".join(failed),
            )

    def _run_once(self, experiment: ExperimentVariant, orchestration_timeout: float, randomize: bool):
        """Deploy, prepare, load, observe, store and tear down one run of one variant"""
        run_start = time.monotonic()
        self.spec = experiment.spec
        self.orchestrator = KubernetesOrchestrator(
            experiment_config=self.spec,
        )
        self.runner = ExperimentRunner(
            config=self.spec,
            config_filename=self.config,
            treatment_registry=self.treatment_registry,
            random_treatment_order=randomize,
            orchestrator=self.orchestrator,
            variant=experiment.variant,
        )
        logger.info(f"Run id is {self.runner.short_id}")
        self.reporter.begin_run(self.runner)
        # from here on the SUE is torn down if anything goes wrong, even a partial deploy
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
        # entered before start(), so teardown() also kills a generator that fails or is interrupted while starting
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
        metadata = {
            "spec": self.config,
            "variant": self.runner.variant.id,
            "factors": self.runner.variant.factors,
            "run": self.runner.short_id,
        }
        for _, response in self.runner.observer.variables().items():
            if response.data is None:
                logger.warning(f"Skipping {response.name}, no data was captured")
                continue
            write_dataframe(
                dataframe=response.data,
                experiment_key=self.runner.experiment_key,
                run_key=self.runner.short_id,
                response_key=response.name,
                metadata=metadata,
            )
            logger.info(f"Wrote {response.name} with {len(response.data)} rows to store")
            if self.report_path:
                for _, treatment in self.runner.treatments.items():
                    self.reporter.gather_interaction(
                        experiment=self.runner,
                        treatment=treatment,
                        response=response,
                    )
                    logger.debug(f"Gathered interaction data for {treatment} and {response}")
                self.reporter.assemble_interaction_data(run_key=self.runner.short_id)
                logger.debug("Assembled all interaction data")
                if self.generator.env is not None:
                    self.reporter.add_loadgen_data(runner=self.runner, request_stats=self.generator.env.stats)
                else:
                    self.reporter.add_loadgen_data_kubernetes_locust(self.generator, self.runner)
                logger.debug("Added load generation data")
        self.teardown()

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
