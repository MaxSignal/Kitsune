"""
Environment variable assignments are stored there.
No transformation allowed, therefore all variables there are strings.

TODO: deal with `config.py` file
"""

import os
import config

flask_env = os.getenv('FLASK_ENV', 'development')
download_path = '/storage'  # Deprecated!!!
webserver_port = os.getenv('WEBSERVER_PORT', '80')
pg_user = config.database_user
pg_password = config.database_password
pg_host = config.database_host
pg_dbname = config.database_dbname
pg_port = config.database_port
