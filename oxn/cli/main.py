"""
Purpose: Main script to initialize and run the experiment.
Functionality: Parses command-line arguments, initializes logging, creates an Engine instance, and runs the experiment.
Connection: Central coordination script that ties together argument parsing, logging, and experiment execution.
"""

import logging
import sys

from oxn.cli.argparser import parse_oxn_args
from oxn.cli.installer import Installer
from oxn.cli.plan import describe_plan, expanded_specs
from oxn.common.errors import OxnException
from oxn.common.log import initialize_logging, log_exception
from oxn.core.context import Context
from oxn.core.engine import Engine
from oxn.core.schema import schema_text
from oxn.core.validation import load_variants
from oxn.orchestration.deployment import Deployment
from oxn.treatments.registry import TreatmentRegistry

logger = logging.getLogger(__name__)


def manage_sue(args):
    """
    Apply or remove the deployment section of a spec without running the experiment

    If the selected variants of the spec's matrix deploy different things, --only has to narrow them down first.
    """
    # the treatments don't matter here, and extension treatments are not loaded
    variants = load_variants(args.spec, check_treatments=False, only=args.only)
    deployments = []
    for experiment in variants:
        if experiment.spec.experiment.deployment not in deployments:
            deployments.append(experiment.spec.experiment.deployment)
    if len(deployments) > 1:
        raise OxnException(
            message=f"The selected variants of {args.spec} deploy {len(deployments)} different setups",
            explanation="Select one with --only, the variants are "
            + "; ".join(experiment.variant.id for experiment in variants),
        )
    deployment = Deployment.from_experiment_spec(variants[0].spec)
    if deployment is None:
        raise OxnException(message=f"Experiment spec {args.spec} has no deployment section")
    if args.command == "deploy":
        deployment.deploy()
    else:
        deployment.teardown()


def main():
    args = parse_oxn_args(sys.argv[1:])
    initialize_logging(loglevel=args.log_level, logfile=args.log_file)
    logger.debug(f"Arguments: {vars(args)}")
    logger.info(f"Hello from oxn {args.command} command. Log level is {args.log_level}.")
    if args.command == "setup":
        sys.exit(Installer(yes=args.yes, dry_run=args.dry_run).run())
    if args.command == "schema":
        write_schema(args)
        return
    if args.command == "plan":
        try:
            plan_experiment(args)
        except OxnException as e:
            log_exception(logger, e)
            sys.exit(1)
        return
    if args.command in ("deploy", "teardown"):
        try:
            manage_sue(args)
        except OxnException as e:
            log_exception(logger, e)
            sys.exit(1)
        return
    run_experiment(args)


def write_schema(args):
    """Write the JSON schema of specs, with the treatments of --extend if given"""
    text = schema_text(TreatmentRegistry(Context(treatment_file_path=args.extend).load_treatment_file()))
    if args.output == "-":
        print(text, end="")
        return
    with open(args.output, "w") as fp:
        fp.write(text)
    print(f"Wrote {args.output}")


def plan_experiment(args):
    """Expand and validate a spec like a run would, and print its runs"""
    registry = TreatmentRegistry(Context(treatment_file_path=args.extend).load_treatment_file())
    variants = load_variants(args.spec, treatments=registry, only=args.only)
    print(describe_plan(args.spec, variants, times=args.times))
    if args.print_specs:
        print(expanded_specs(variants), end="")


def run_experiment(args):
    engine = Engine(
        configuration_path=args.spec,
        report_path=args.report,
        treatment_file=args.extend,
        keep_sue=args.keep_sue,
        only=args.only,
        fail_fast=args.fail_fast,
    )
    try:
        engine.load_experiment_specification()
    except OxnException as e:
        log_exception(logger, e)
        sys.exit(1)
    try:
        engine.run(
            runs=args.times,
            orchestration_timeout=args.timeout,
            randomize=args.randomize,
            randomize_variants=args.randomize_variants,
        )
    except OxnException as oxn_exception:
        log_exception(logger, oxn_exception)
        logger.info(f"Stopped in phase {engine.phase.value}")
        failed = True
    except KeyboardInterrupt:
        logger.info(f"Interrupted in phase {engine.phase.value}. Trying to shut down gracefully. Press ctrl-c to force")
        failed = True
    else:
        failed = False
    finally:
        engine.teardown()
    if failed:
        sys.exit(1)
