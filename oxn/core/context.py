"""

Purpose: Manages the execution context and dynamically loads user-defined treatments.
Functionality: Loads and validates treatment classes from a specified file.
Connection: Allows the application to dynamically include custom treatments defined by the user.

Module for providing an execution context to experiments

heavily inspired by https://github.com/locustio/locust
"""

import importlib.util
import inspect
import os
import sys
from typing import List

from oxn.models.treatment import Treatment


class Context:
    """
    Provide an execution context to experiments by loading user-defined treatment files

    This class can eventually be used to also load custom response variable implementations and locustfiles
    """

    def __init__(self, treatment_file_path):
        self.treatment_path = treatment_file_path

    @staticmethod
    def is_treatment_class(thing) -> bool:
        """A thing is a treatment class if it is a class, and a subclass of treatment, and not an abstract treatment"""
        return bool(inspect.isclass(thing) and issubclass(thing, Treatment) and not inspect.isabstract(thing))

    def load_treatment_file(self) -> List[Treatment]:
        """Load user-supplied treatments from a file"""
        if not self.treatment_path:
            return []
        sys.path.insert(0, os.getcwd())
        directory, treatment_file = os.path.split(self.treatment_path)
        in_python_path = False
        path_index = None

        if directory not in sys.path:
            sys.path.insert(0, directory)
            in_python_path = True
        else:
            # move the dir to front of path so it gets preferential treatment
            idx = sys.path.index(directory)
            if idx != 0:
                path_index = idx
                sys.path.insert(0, directory)
                del sys.path[idx + 1]
        module_name = os.path.splitext(treatment_file)[0]
        module_spec = importlib.util.spec_from_file_location(module_name, self.treatment_path)
        assert module_spec is not None and module_spec.loader is not None
        imported = importlib.util.module_from_spec(module_spec)
        # registered like SourceFileLoader.load_module did, so the treatments can be pickled and imported again
        sys.modules[module_name] = imported
        module_spec.loader.exec_module(imported)
        if in_python_path:
            # cleanup
            del sys.path[0]
        if path_index is not None:
            sys.path.insert(path_index + 1, directory)
            del sys.path[0]

        # iterate over vars of the imported module and find the treatment implementations
        treatment_classes = [value for key, value in vars(imported).items() if self.is_treatment_class(value)]
        return treatment_classes
