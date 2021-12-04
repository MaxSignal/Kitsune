from distutils.util import strtobool

from .vars import ENV_VARS


class DERIVED_VARS:
    IS_DEVELOPMENT = ENV_VARS.FLASK_ENV == 'development'
    DATABASE_URL = f'postgres://{ENV_VARS.DATABASE_USER}:{ENV_VARS.DATABASE_PASSWORD}@{ENV_VARS.DATABASE_HOST}/{ENV_VARS.DATABASE_NAME}'
    PROXY_LIST = str(ENV_VARS.PROXIES).split(",")
    IS_PUBSUB_ENABLED = strtobool(ENV_VARS.PUBSUB)
    REDIS_NODE_OPTIONS = dict(
        host=ENV_VARS.REDIS_HOST,
        port=ENV_VARS.REDIS_PORT,
        password=ENV_VARS.REDIS_PASSWORD
    )
