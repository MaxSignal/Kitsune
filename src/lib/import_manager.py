from ..internals.utils.logger import log
from src.internals.cache import redis
from src.internals.database import database
import logging


def import_posts(import_id, target, args):
    logging.basicConfig(filename='kemono_importer.log', level=logging.DEBUG)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    database.init()
    redis.init()
    try:
        target(import_id, *args)
    except KeyboardInterrupt:
        return
    except SystemExit:
        return
    except:
        log(import_id, 'Internal error. Contact site staff on Telegram.', 'exception')
    
    # cleanup on "internal" exit
    redis.delete_keys([f'imports:{import_id}'])
    redis.delete_keys_pattern([f'running_imports:*:{import_id}'])
