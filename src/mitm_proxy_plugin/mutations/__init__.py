"""
Mutations module for the MITM Proxy plugin.
It includes a catalog of mutants and functions to apply mutations to HTTP flows.
"""
from .catalog import MutantCatalog
from .operators import apply_mutation

__all__ = [
    "MutantCatalog",
    "apply_mutation",
]