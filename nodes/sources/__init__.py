"""Job sources. get_source("indeed") -> the module nodes/sources/indeed.py"""

import importlib


def get_source(name: str):
    return importlib.import_module(f"nodes.sources.{name}")
