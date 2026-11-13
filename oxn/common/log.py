"""
Purpose: Configures logging for the application.
Functionality: Initializes and configures logging settings based on provided log level and optional log file.
Connection: Used by main.py to set up logging.

Logging configuration for oxn"""
import logging
import socket
import logging.config

from konsole import SGR, KonsoleFormatter

HOSTNAME = socket.gethostname()


class ConsoleFormatter(KonsoleFormatter):
    """Colored console output from konsole, which uses color only if stderr is a terminal"""

    STYLE = {**KonsoleFormatter.STYLE, "INFO": SGR("1;36", "0;39")}
    """konsole leaves info messages uncolored, which would be most of the output of an experiment"""
    PUNCTUATION = ("",)
    """Every message ends with the empty string, this stops konsole from appending a period to commands and paths"""

    def formatMessage(self, record):
        origin = f"{self.formatTime(record, '%H:%M:%S')} {record.name}"
        return f"{self.applyStyle(self.DETAIL, origin)} {super().formatMessage(record)}"


def initialize_logging(loglevel, logfile=None):
    loglevel = loglevel.upper()

    LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": f"[%(asctime)s] {HOSTNAME}/%(levelname)s/%(name)s: %(message)s",
            },
            "plain": {
                "format": "%(message)s",
            },
            "console": {
                "()": ConsoleFormatter,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
            },
        },
        "loggers": {
            "oxn": {
                "handlers": ["console"],
                "level": loglevel,
                "propagate": False,
            },
        },
        "root": {"level": loglevel, "handlers": ["console"]},
    }
    if logfile:
        LOGGING_CONFIG["handlers"]["file"] = {
            "class": "logging.FileHandler",
            "filename": logfile,
            "formatter": "default",
        }
        LOGGING_CONFIG["root"]["handlers"] = ["file"]
        LOGGING_CONFIG["loggers"]["oxn"]["handlers"] = ["file"]

    logging.config.dictConfig(LOGGING_CONFIG)
