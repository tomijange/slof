import logging
import unittest

from oxn.common.log import ConsoleFormatter


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
