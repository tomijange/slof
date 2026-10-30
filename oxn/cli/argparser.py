""" 
Purpose: Handles command-line argument parsing.
Functionality: Defines and validates the command-line arguments required to run the experiment.
Connection: Used by main.py to parse and validate input arguments.
 """

import argparse
import os

from oxn.common.utils import time_string_to_seconds


def validate_file(file):
    if not os.path.exists(file):
        raise argparse.ArgumentTypeError(
            f"Experiment specification {file} does not exist"
        )
    return file


def add_logging_options(target, default_level="info"):
    """
    Add the options shared by the experiment command and all subcommands

    Not a parent parser, parsers share the actions of their parents, so a different default for one would apply to all
    """
    target.add_argument(
        "--loglevel",
        dest="log_level",
        choices=["debug", "info", "warning", "error", "critical"],
        nargs="?",
        default=default_level,
        help=f"Set the log level. Choose between debug, info, warning, error, critical. Default is {default_level}",
    )
    target.add_argument(
        "--logfile",
        dest="log_file",
        type=str,
        help="Write logs to a file. If the file does not exist, it will be created.",
    )


parser = argparse.ArgumentParser(
    prog="oxn",
    description="Observability experiments engine",
    usage="%(prog)s [-h] spec [options]\n       %(prog)s {setup,deploy,teardown} ...",
    epilog="Other commands: 'oxn setup' guides you through preparing a cluster, 'oxn deploy <spec>' and "
    "'oxn teardown <spec>' apply and remove the deployment section of a spec without running the experiment. "
    "Use 'oxn <command> --help' for details.",
)
parser.set_defaults(command="run")
add_logging_options(parser)

parser.add_argument(
    "spec",
    action="store",
    type=validate_file,
    help="Path to an oxn experiment specification to execute.",
)
parser.add_argument(
    "--times", default=1, type=int, help="Run the experiment n times. Default is 1"
)
parser.add_argument(
    "--report",
    dest="report",
    type=str,
    help="Create an experiment report in the specified directory. Make sure that the directory exists. The report will be named report_<timestamp>.yaml",
)
parser.add_argument(
    "--accounting",
    action="store_true",
    help="Capture resource usage for oxn and the sue. Requires that the report option is set."
    "Will increase the time it takes to run the experiment by about "
    "two seconds for each service in the sue.",
)
parser.add_argument(
    "--randomize",
    action="store_true",
    help="Randomize the treatment execution order. Per default, treatments are executed in the order given in the "
    "experiment specification",
)
parser.add_argument(
    "--extend",
    dest="extend",
    type=validate_file,
    help="Path to a treatment extension file. If specified, treatments in the file will be loaded into oxn.",
)

parser.add_argument(
    "--timeout",
    default="1m",
    help="Timeout after which we stop trying to build the SUE. Default is 1m",
    type=time_string_to_seconds
)

parser.add_argument(
    "--keep-sue",
    dest="keep_sue",
    action="store_true",
    help="Do not tear down the SUE after the experiment, e.g. to inspect it. Tear it down later with oxn teardown <spec>",
)


setup_parser = argparse.ArgumentParser(
    prog="oxn setup",
    description="Guide through installing the tools that stay on the cluster between experiments: "
    "OpenEBS, Prometheus and Kepler. Experiment specs deploy everything else themselves.",
)
setup_parser.set_defaults(command="setup")
add_logging_options(setup_parser, default_level="warning")
setup_parser.add_argument(
    "--yes",
    action="store_true",
    help="Do not ask, install everything that is missing. For scripts.",
)
setup_parser.add_argument(
    "--dry-run",
    dest="dry_run",
    action="store_true",
    help="Only show what is installed and the commands that would run. Changes nothing.",
)

deploy_parser = argparse.ArgumentParser(
    prog="oxn deploy",
    description="Deploy the deployment section of an experiment specification without running the experiment.",
)
deploy_parser.set_defaults(command="deploy")

teardown_parser = argparse.ArgumentParser(
    prog="oxn teardown",
    description="Remove the deployment section of an experiment specification from the cluster.",
)
teardown_parser.set_defaults(command="teardown")

for spec_parser in (deploy_parser, teardown_parser):
    add_logging_options(spec_parser)
    spec_parser.add_argument(
        "spec",
        action="store",
        type=validate_file,
        help="Path to an oxn experiment specification with a deployment section.",
    )

subcommand_parsers = {"setup": setup_parser, "deploy": deploy_parser, "teardown": teardown_parser}


def parse_oxn_args(args):
    if args and args[0] in subcommand_parsers:
        return subcommand_parsers[args[0]].parse_args(args[1:])
    args = parser.parse_args(args)
    if args.accounting and not args.report:
        parser.error("The --accounting option requires the --report option to be set")
    return args
