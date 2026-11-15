import logging
import unittest

from oxn.common.log import ConsoleFormatter, log_exception


def record(level=logging.INFO, message="Deployed helm release"):
    return logging.LogRecord(
        name="oxn.core.engine",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


class ConsoleFormatterTest(unittest.TestCase):
    def test_it_colors_levels_for_a_terminal(self):
        formatter = ConsoleFormatter(use_color=True)
        self.assertIn("\x1b[1;36m[INFO]", formatter.format(record()))
        self.assertIn("\x1b[1;31m[ERROR]", formatter.format(record(level=logging.ERROR)))

    def test_it_uses_no_escape_codes_without_a_terminal(self):
        formatter = ConsoleFormatter(use_color=False)
        self.assertNotIn("\x1b", formatter.format(record()))

    def test_it_keeps_the_time_and_origin_of_a_message(self):
        formatter = ConsoleFormatter(use_color=False)
        self.assertRegex(
            formatter.format(record()),
            r"^\d\d:\d\d:\d\d oxn\.core\.engine \[INFO\] Deployed helm release$",
        )

    def test_it_does_not_change_commands(self):
        formatter = ConsoleFormatter(use_color=False)
        message = "$ kubectl apply -f k8s/kibana"
        self.assertTrue(formatter.format(record(message=message)).endswith(message))


class LogExceptionTest(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("oxn.tests.log_exception")

    def test_it_logs_the_class_name_and_message_as_error(self):
        self.logger.setLevel(logging.INFO)
        with self.assertLogs(self.logger, level=logging.INFO) as logs:
            log_exception(self.logger, ValueError("bad spec"))
        self.assertEqual(logs.records[0].levelno, logging.ERROR)
        self.assertEqual(logs.records[0].getMessage(), "ValueError: bad spec")
        self.assertFalse(logs.records[0].exc_info)

    def test_it_prefixes_a_message_and_uses_the_given_level(self):
        self.logger.setLevel(logging.INFO)
        with self.assertLogs(self.logger, level=logging.INFO) as logs:
            log_exception(self.logger, ValueError("timeout"), "Failed to capture latency", level=logging.WARNING)
        self.assertEqual(logs.records[0].levelno, logging.WARNING)
        self.assertEqual(logs.records[0].getMessage(), "Failed to capture latency: ValueError: timeout")

    def test_it_includes_the_stack_trace_on_debug_level(self):
        self.logger.setLevel(logging.DEBUG)
        try:
            raise ValueError("bad spec")
        except ValueError as e:
            with self.assertLogs(self.logger, level=logging.DEBUG) as logs:
                log_exception(self.logger, e)
        self.assertIs(logs.records[0].exc_info[0], ValueError)
