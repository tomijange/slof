"""
Purpose: Handles command-line argument parsing.
Functionality: Defines and validates the command-line arguments required to run the experiment.
Connection: Used by main.py to parse and validate input arguments.
"""

import argparse
import os

from oxn.common.utils import time_string_to_seconds

DEFAULT_SCHEMA_PATH = "schema.json"
"""Where oxn schema writes the schema, in the root of the repository. Kept here, so --help does not import oxn.core"""


def validate_file(file):
    if not os.path.exists(file):
        raise argparse.ArgumentTypeError(f"Experiment specification {file} does not exist")
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


def add_only_option(target):
    """Add the option that selects variants of a spec's matrix"""
    target.add_argument(
        "--only",
        dest="only",
        action="append",
        default=[],
        metavar="AXIS=LEVEL",
        help="Only use the variants of the spec's matrix with this level, for example --only sampling=10.0. "
        "Repeat it for several levels: levels of one axis are alternatives, levels of different axes must all match.",
    )


parser = argparse.ArgumentParser(
    prog="oxn",
    description="Observability experiments engine",
    usage="%(prog)s [-h] spec [options]\n       %(prog)s {setup,plan,deploy,teardown,schema} ...",
    epilog="Other commands: 'oxn setup' guides you through preparing a cluster, 'oxn plan <spec>' lists the runs "
    "of a spec and its matrix, 'oxn deploy <spec>' and 'oxn teardown <spec>' apply and remove the deployment "
    "section of a spec without running the experiment, 'oxn schema' writes the JSON schema of specs for editors. "
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
    "--times",
    default=1,
    type=int,
    help="Run every variant of the experiment n times, one round of all variants after the other. Default is 1",
)
parser.add_argument(
    "--report",
    dest="report",
    type=str,
    help="Create an experiment report in the specified directory. Make sure that the directory exists. The report will be named report_<timestamp>.yaml",
)
parser.add_argument(
    "--randomize",
    action="store_true",
    help="Randomize the treatment execution order. Per default, treatments are executed in the order given in the "
    "experiment specification",
)
parser.add_argument(
    "--randomize-variants",
    dest="randomize_variants",
    action="store_true",
    help="Run the variants of the spec's matrix in a new random order in every round. Per default, every round "
    "runs them in the order of the matrix",
)
parser.add_argument(
    "--fail-fast",
    dest="fail_fast",
    action="store_true",
    help="Stop at the first failed run. Per default, a failed run is torn down and the next run starts",
)
add_only_option(parser)
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
    type=time_string_to_seconds,
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
    add_only_option(spec_parser)

plan_parser = argparse.ArgumentParser(
    prog="oxn plan",
    description="Expand and validate an experiment specification and list the runs 'oxn <spec>' would do, "
    "without touching the cluster.",
)
plan_parser.set_defaults(command="plan")
add_logging_options(plan_parser, default_level="warning")
plan_parser.add_argument(
    "spec",
    action="store",
    type=validate_file,
    help="Path to an oxn experiment specification.",
)
add_only_option(plan_parser)
plan_parser.add_argument("--times", default=1, type=int, help="Runs of every variant to plan for. Default is 1")
plan_parser.add_argument(
    "--extend",
    dest="extend",
    type=validate_file,
    help="Path to a treatment extension file, to check the treatments it defines.",
)
plan_parser.add_argument(
    "--print",
    dest="print_specs",
    action="store_true",
    help="Also print the expanded specification of every variant.",
)

schema_parser = argparse.ArgumentParser(
    prog="oxn schema",
    description="Write the JSON schema of experiment specs, which editors use for completion and checks. "
    "The specs in experiments/ name it in their first line.",
)
schema_parser.set_defaults(command="schema")
add_logging_options(schema_parser, default_level="warning")
schema_parser.add_argument(
    "--output",
    default=DEFAULT_SCHEMA_PATH,
    help=f"Where to write the schema, - for stdout. Default is {DEFAULT_SCHEMA_PATH}",
)
schema_parser.add_argument(
    "--extend",
    dest="extend",
    type=validate_file,
    help="Path to a treatment extension file, to include the treatments it defines.",
)

subcommand_parsers = {
    "setup": setup_parser,
    "plan": plan_parser,
    "deploy": deploy_parser,
    "teardown": teardown_parser,
    "schema": schema_parser,
}


def parse_oxn_args(args):
    if args and args[0] in subcommand_parsers:
        return subcommand_parsers[args[0]].parse_args(args[1:])
    args = parser.parse_args(args)
    return args
