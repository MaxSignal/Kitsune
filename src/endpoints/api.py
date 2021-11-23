from flask import Blueprint, request
import json
import os
import config
import threading

from ..internals.cache.redis import get_redis
from ..internals.utils import thread_master
from ..internals.utils.flask_thread import FlaskThread
from ..internals.utils.utils import get_import_id
from ..internals.utils.encryption import encrypt_and_log_session
from ..internals.utils import logger
from ..lib.import_manager import import_posts
from ..lib.autoimport import decrypt_all_good_keys, log_import_id, revoke_v1_key, encrypt_and_save_session_for_auto_import
from ..internals.utils.download import uniquify
from werkzeug.utils import secure_filename

from ..importers import patreon
from ..importers import fanbox
from ..importers import subscribestar
from ..importers import gumroad
from ..importers import discord
from ..importers import fantia
api = Blueprint('api', __name__)


@api.route('/api/autoimport', methods=['POST'])
def autoimport_api():
    prv_key = request.form.get('private_key')

    if not prv_key:
        return "No private key provided.", 401

    # migrate v1 (no hash) keys
    keys_to_migrate = None
    try:
        keys_to_migrate = decrypt_all_good_keys(prv_key, v1=True)
    except:
        return "(v1) Error while decrypting session tokens. The private key may be incorrect.", 401

    for key in keys_to_migrate:
        encrypt_and_save_session_for_auto_import(
            key['service'], key['decrypted_key'], contributor_id=key['contributor_id'], discord_channel_ids=key['discord_channel_ids'])
        revoke_v1_key(key['id'])

    keys_to_import = None
    try:
        keys_to_import = decrypt_all_good_keys(prv_key)
    except:
        return "Error while decrypting session tokens. The private key may be incorrect.", 401

    for key in keys_to_import:
        redis = get_redis()
        import_id = get_import_id(key['decrypted_key'])
        log_import_id(key['id'], import_id)
        data = {
            'key': key['decrypted_key'],
            'key_id': key['id'],
            'service': key['service'],
            'channel_ids': key['discord_channel_ids'],
            'auto_import': None,
            'save_session_key': None,
            'save_dms': None,
            'contributor_id': key['contributor_id']
        }
        redis.set('imports:' + import_id, json.dumps(data))

    return '', 200


@api.route('/api/import', methods=['POST'])
def import_api():
    key = request.form.get('session_key')
    import_id = get_import_id(key)
    service = request.form.get('service')
    allowed_to_auto_import = request.form.get('auto_import', False)
    allowed_to_save_session = request.form.get('save_session_key', False)
    allowed_to_scrape_dms = request.form.get('save_dms', False)
    channel_ids = request.form.get('channel_ids')
    contributor_id = request.form.get('contributor_id')

    if not key:
        return "", 401

    if key and service and allowed_to_save_session:
        encrypt_and_log_session(import_id, service, key)

    target = None
    args = None
    if service == 'patreon':
        target = patreon.import_posts
        args = (key, allowed_to_scrape_dms, contributor_id, allowed_to_auto_import, None)
    elif service == 'fanbox':
        target = fanbox.import_posts
        args = (key, contributor_id, allowed_to_auto_import, None)
    elif service == 'subscribestar':
        target = subscribestar.import_posts
        args = (key, contributor_id, allowed_to_auto_import, None)
    elif service == 'gumroad':
        target = gumroad.import_posts
        args = (key, contributor_id, allowed_to_auto_import, None)
    elif service == 'fantia':
        target = fantia.import_posts
        args = (key, contributor_id, allowed_to_auto_import, None)
    elif service == 'discord':
        target = discord.import_posts
        args = (key, channel_ids.strip().replace(" ", ""), contributor_id, allowed_to_auto_import, None)

    if target is not None and args is not None:
        logger.log(import_id, f'Starting import. Your import id is {import_id}.')
        FlaskThread(target=import_posts, args=(import_id, target, args)).start()
    else:
        logger.log(import_id, f'Error starting import. Your import id is {import_id}.')

    return import_id, 200


@api.route('/api/logs/<import_id>', methods=['GET'])
def get_logs(import_id):
    logs = logger.get_logs(import_id)
    return json.dumps(logs), 200


@api.route('/api/upload/<path:path>', methods=['POST'])
def upload_file(path):
    if 'file' not in request.files:
        return 'No file', 400
    uploaded_file = request.files['file']
    os.makedirs(os.path.join(config.download_path, path), exist_ok=True)
    filename = uniquify(os.path.join(config.download_path, path, secure_filename(uploaded_file.filename)))
    uploaded_file.save(os.path.join(config.download_path, path, filename))
    return os.path.join('/', path, filename), 200


@api.route('/api/active_imports', methods=['GET'])
def get_thread_count():
    return str(threading.active_count()), 200
