"""Backward compatibility alias for utility helpers.

This package mirrors :mod:`zundamotion.utils` so legacy imports like
``zundamotion.components.utils`` continue to work after the components
refactor.
"""
from __future__ import annotations

import sys as _sys

from ... import utils as _utils

# Expose the root `zundamotion.utils` package under the components namespace.
_sys.modules[__name__] = _utils
