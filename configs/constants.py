"""
This module holds various constants not related to environment variables.
Therefore no exported functions allowed.
"""

from pathlib import Path

project_path = Path(__file__, '..', '..').resolve()
DEV_PATH = project_path.joinpath(project_path, 'development')
