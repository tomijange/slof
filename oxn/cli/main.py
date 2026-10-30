""" 
Purpose: Main script to initialize and run the experiment.
Functionality: Parses command-line arguments, initializes logging, creates an Engine instance, and runs the experiment.
Connection: Central coordination script that ties together argument parsing, logging, and experiment execution.
 """

import logging
import sys

from oxn.core.engine import Engine
from oxn.common.errors import OxnException
from oxn.common.log import initialize_logging
from oxn.core.validation import load_experiment_specification
from oxn.orchestration.deployment import Deployment
from oxn.cli.argparser import parse_oxn_args
from oxn.cli.installer import Installer

logger = logging.getLogger(__name__)


def log_exception(exception):
    """Log an exception with its class name, including the stack trace on the debug level"""
    logger.error(
        f"{exception.__class__.__name__}: {exception}",
        exc_info=logger.isEnabledFor(logging.DEBUG),
    )


def manage_sue(args):
    """Apply or remove the deployment section of a spec without running the experiment"""
    deployment = Deployment.from_experiment_spec(load_experiment_specification(args.spec))
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
    if args.command in ("deploy", "teardown"):
        try:
            manage_sue(args)
        except OxnException as e:
            log_exception(e)
            sys.exit(1)
        return
    run_experiment(args)


def run_experiment(args):
    engine = Engine(
        configuration_path=args.spec,
        report_path=args.report,
        treatment_file=args.extend,
    )
    try:
        engine.load_experiment_specification()
    except OxnException as e:
        log_exception(e)
        sys.exit(1)
    try:
        engine.run(
            runs=args.times,
            orchestration_timeout=args.timeout,
            randomize=args.randomize,
            accounting=args.accounting,
            keep_sue=args.keep_sue,
        )
    except OxnException as oxn_exception:
        log_exception(oxn_exception)
    except KeyboardInterrupt:
        logger.info("Trying to shut down gracefully. Press ctrl-c to force")
    finally:
        if engine.loadgen_running:
            engine.generator.kill()
            logger.info("Shut down load generation")
        if engine.sue_running and not args.keep_sue:
            # TODO: call cleanup methods here
            engine.orchestrator.teardown()
            logger.info("Shut down sue")
