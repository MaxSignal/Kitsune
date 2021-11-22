import config
import redis
import random
import string
import time
import json
from threading import Thread
from src.internals.utils import logger
from src.internals.utils.encryption import encrypt_and_log_session
from src.lib.import_manager import import_posts
from ..cache.redis import get_redis, delete_keys, delete_keys_pattern, scan_keys
from src.importers import patreon
from src.importers import fanbox
from src.importers import subscribestar
from src.importers import gumroad
from src.importers import discord
from src.importers import fantia
from setproctitle import setthreadtitle
# a function that first runs existing import requests in a staggered manner (they may be incomplete as importers should delete their keys when they are done) then watches redis for new keys and handles queueing
# needs to be run in a thread itself
# remember to clear logs after successful import
def watch(queue_limit=config.pubsub_queue_limit):
    archiver_id = ''.join(random.choice(string.ascii_letters + string.digits) for x in range(16))
    delete_keys_pattern([f"running_imports:*"])
    setthreadtitle(f'KWATCHER')
    print(f'Key watcher ({archiver_id}) is starting!')

    redis = get_redis()
    threads_to_run = []
    while True:
        for thread in threads_to_run:
            if not thread.is_alive():
                threads_to_run.remove(thread)
        
        for key in scan_keys('imports:*'):
            key_data = redis.get(key)
            if key_data:
                import_id = key.split(':')[1]
                try:
                    key_data = json.loads(key_data)
                except json.decoder.JSONDecodeError:
                    print(f'An decoding error occured while processing import request {key.decode("utf-8")}; are you sending malformed JSON?')
                    delete_keys([key])
                    continue
                
                if redis.get(f"running_imports:{archiver_id}:{import_id}"):
                    continue

                if len(threads_to_run) < queue_limit:
                    try:
                        target = None
                        args = None
                        # data = {
                        #     'key': key,
                        #     'key_id': key_id,
                        #     'service': service,
                        #     'allowed_to_auto_import': allowed_to_auto_import,
                        #     'allowed_to_save_session': allowed_to_save_session,
                        #     'allowed_to_scrape_dms': allowed_to_scrape_dms,
                        #     'channel_ids': channel_ids,
                        #     'contributor_id': contributor_id
                        # }
                        service_key = key_data['key']
                        key_id = key_data.get('key_id', None)
                        service = key_data['service']
                        allowed_to_auto_import = key_data.get('auto_import', False)
                        allowed_to_save_session = key_data.get('save_session_key', False)
                        allowed_to_scrape_dms = key_data.get('save_dms', False)
                        channel_ids = key_data.get('channel_ids')
                        contributor_id = key_data.get('contributor_id')

                        if service_key and service and allowed_to_save_session:
                            try:
                                encrypt_and_log_session(import_id, service, service_key)
                            except:
                                logger.log(import_id, 'Exception occured while logging session.', 'exception', to_client=False)

                        if service == 'patreon':
                            target = patreon.import_posts
                            args = (service_key, allowed_to_scrape_dms, contributor_id, allowed_to_auto_import, key_id)
                        elif service == 'fanbox':
                            target = fanbox.import_posts
                            args = (service_key, contributor_id, allowed_to_auto_import, key_id)
                        elif service == 'subscribestar':
                            target = subscribestar.import_posts
                            args = (service_key, contributor_id, allowed_to_auto_import, key_id)
                        elif service == 'gumroad':
                            target = gumroad.import_posts
                            args = (service_key, contributor_id, allowed_to_auto_import, key_id)
                        elif service == 'fantia':
                            target = fantia.import_posts
                            args = (service_key, contributor_id, allowed_to_auto_import, key_id)
                        elif service == 'discord':
                            target = discord.import_posts
                            if channel_ids is None:
                                channel_ids = ''
                            args = (service_key, channel_ids.strip().replace(" ", ""), contributor_id, allowed_to_auto_import, key_id)
                        else:
                            logger.log(import_id, f'Service "{service}" unsupported.')
                            delete_keys([key])
                            continue

                        if target is not None and args is not None:
                            logger.log(import_id, f'Starting import. Your import id is {import_id}.')
                            thread = Thread(target=import_posts, args=(import_id, target, args))
                            thread.start()
                            threads_to_run.append(thread)
                            redis.set(f"running_imports:{archiver_id}:{import_id}", '1')
                        else:
                            logger.log(import_id, f'Error starting import. Your import id is {import_id}.')
                    except KeyError:
                        logger.log(import_id, 'Exception occured while starting import due to missing data in payload.', 'exception', to_client=True)
                        delete_keys([key])
        
        time.sleep(1)