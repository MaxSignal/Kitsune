from src.internals.utils.encryption import encrypt_and_log_session
from src.internals.database import database
from ..internals.utils.logger import log
from src.internals.cache import redis
import logging
import json


def import_posts(import_id, target, args):
    logging.basicConfig(filename='kemono_importer.log', level=logging.DEBUG)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    database.init()
    redis.init()

    ''' Log. '''
    r = redis.get_redis()
    data = json.loads(r.get(f'imports:{import_id}'))
    if data.get('save_session_key', False):
        try:
            encrypt_and_log_session(import_id, data)
        except:
            log(import_id, 'Exception occured while logging session.', 'exception', to_client=False)

    try:
        target(import_id, *args)
    except KeyboardInterrupt:
        return
    except SystemExit:
        return
    except:
        log(import_id, 'Internal error. Contact site staff on Telegram.', 'exception')

    ''' Update log. '''
    if data.get('save_session_key', False):
        updated_data = json.loads(r.get(f'imports:{import_id}'))
        if updated_data != data:
            try:
                encrypt_and_log_session(import_id, data)
            except:
                log(import_id, 'Exception occured while updating session log.', 'exception', to_client=False)

    ''' Cleanup on "internal" exit. '''
    redis.delete_keys([f'imports:{import_id}'])
    redis.delete_keys_pattern([f'running_imports:*:{import_id}'])
