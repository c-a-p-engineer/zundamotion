import asyncio
import logging
import pathlib
import subprocess
import sys

import pytest

sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from zundamotion.utils.ffmpeg_runner import run_ffmpeg_async


def test_run_ffmpeg_async_no_error_logs(caplog):
    """error_log_levelをWARNINGにするとERRORログが出ない"""
    with caplog.at_level(logging.ERROR, logger="zundamotion"):
        with pytest.raises(subprocess.CalledProcessError):
            asyncio.run(
                run_ffmpeg_async(["bash", "-c", "exit 1"], error_log_level=logging.WARNING)
            )
    assert not caplog.records
