"""
Variables which derive off environment variables go there.
"""
from pathlib import Path

from .vars import flask_env, download_path, pg_dbname, pg_host, pg_password, pg_user, pg_port

is_development = flask_env == 'development'
temp_dir_root = Path(download_path, 'data', 'tmp')
data_folder = Path(download_path, 'data')
pg_url = f'postgres://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_dbname}'