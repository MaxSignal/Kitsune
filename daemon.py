from src.internals.database import database
from src.internals.cache import redis
from src.internals.utils import key_watcher, indexer
from src.lib import server
from configs.derived_vars import pg_url
from yoyo import read_migrations, get_backend
from threading import Thread
import logging
import config

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.redis import RedisIntegration

if config.sentry_dsn:
    sentry_sdk.init(
        dsn=config.sentry_dsn,
        integrations=[FlaskIntegration(), RedisIntegration()]
    )

logging.basicConfig(filename='kemono_importer.log', level=logging.DEBUG)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)


database.init()
redis.init()


backend = get_backend(pg_url)
migrations = read_migrations('./migrations')
with backend.lock():
    backend.apply_migrations(backend.to_apply(migrations))


Thread(target=indexer.run).start()
if (config.pubsub):
    Thread(target=key_watcher.watch).start()
Thread(target=server.run).start()
