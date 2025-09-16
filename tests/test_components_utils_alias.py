import importlib


def test_components_utils_alias():
    root_utils = importlib.import_module("zundamotion.utils")
    components_utils = importlib.import_module("zundamotion.components.utils")
    assert components_utils is root_utils

