import os
from typing import List, Optional

from dotenv import load_dotenv

from .constants import CONSTANTS

# TODO: use it later
env_filename = dict(
    development='.env.dev',
    production='.env.prod'
)

load_dotenv(CONSTANTS.PROJECT_PATH.joinpath('.env'))


class ENV_VARS:
    FLASK_ENV = os.getenv('FLASK_ENV')
    SERVER_PORT = os.getenv('KEMONO_ARCHIVER_PORT')
    DATABASE_HOST = os.getenv('DATABASE_HOST')
    DATABASE_NAME = os.getenv('DATABASE_NAME')
    DATABASE_USER = os.getenv('DATABASE_USER')
    DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD')
    REDIS_HOST = os.getenv('REDIS_HOST')
    REDIS_PORT = os.getenv('REDIS_PORT')
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD')
    PROXIES = os.getenv('KEMONO_ARCHIVER_PROXIES')
    BAN_URL = os.getenv('KEMONO_ARCHIVER_BAN_URL')
    PUBKEY = os.getenv('KEMONO_ARCHIVER_PUBKEY')
    SALT = os.getenv('KEMONO_ARCHIVER_SALT')
    PUBSUB = os.getenv('KEMONO_ARCHIVER_PUBSUB')
    PUBSUB_QUEUE_LIMIT = os.getenv('KEMONO_ARCHIVER_PUBSUB_QUEUE_LIMIT')


def validate_vars(var_list: List[Optional[str]]):
    missing_vars = []

    for var in var_list:
        if not getattr(ENV_VARS, var, None):
            missing_vars.append(var)

    if missing_vars:
        var_string = ", ".join(missing_vars)
        raise ValueError(f'These environment variables are not set: {var_string}')


critical_vars = []
validate_vars(critical_vars)
