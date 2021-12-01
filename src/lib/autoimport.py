import hashlib
from base64 import b64decode, b64encode

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes
from joblib import Parallel, delayed
from src.internals.utils.logger import log

from configs.env_vars import ENV_VARS
from src.internals.cache.redis import (
    delete_keys,
    delete_keys_pattern,
    get_redis
)
from src.internals.database.database import (
    get_cursor,
    get_raw_conn,
    return_conn
)


def log_import_id(key_id, import_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO saved_session_key_import_ids (key_id, import_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (int(key_id), import_id))
    conn.commit()
    return_conn(conn)


def revoke_v1_key(key_id):
    # mark as dead (should happen when a key is detected as unusable due to expiration/invalidation)
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_session_keys WHERE id = %s", (int(key_id),))
    conn.commit()
    return_conn(conn)


def kill_key(key_id):
    # mark as dead (should happen when a key is detected as unusable due to expiration/invalidation)
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE saved_session_keys_with_hashes SET dead = TRUE WHERE id = %s", (int(key_id),))
    conn.commit()
    return_conn(conn)


def decrypt_key(key, rsa_key):
    key_to_decrypt = key

    key_der = b64decode(rsa_key.strip())
    key_prv = RSA.importKey(key_der)
    rsa_cipher = PKCS1_OAEP.new(key_prv)

    try:
        if key_to_decrypt['encrypted_key'].startswith('#'):
            # rsa+aes
            cryptstuff = key_to_decrypt['encrypted_key'].split('#')[-1]
            encrypted_aes_key, nonce, ct, tag = (b64decode(x) for x in b64decode(cryptstuff).decode('utf-8').split('|'))
            decrypted_aes_key = rsa_cipher.decrypt(encrypted_aes_key)
            cipher = AES.new(decrypted_aes_key, AES.MODE_EAX, nonce)
            key_to_decrypt['decrypted_key'] = cipher.decrypt_and_verify(ct, tag).decode('utf-8')
        else:
            # rsa solo
            key_to_decrypt['decrypted_key'] = rsa_cipher.decrypt(b64decode(key_to_decrypt['encrypted_key'])).decode('utf-8')
    except:
        return None
    return (key_to_decrypt)


def decrypt_all_good_keys(privatekey, v1=False):

    key_table = 'saved_session_keys' if v1 else 'saved_session_keys_with_hashes'

    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {key_table} WHERE dead = FALSE")
    encrypted_keys = cursor.fetchall()
    decrypted_keys = []
    decrypting = Parallel(n_jobs=-1)(delayed(decrypt_key)(key, privatekey) for key in encrypted_keys)
    for key in decrypting:
        if key:
            decrypted_keys.append(key)
    return decrypted_keys


def encrypt_and_save_session_for_auto_import(service, key, contributor_id=None, discord_channel_ids=None):

    rsa_key_der = b64decode(ENV_VARS.PUBKEY.strip())
    rsa_key_pub = RSA.importKey(rsa_key_der)
    rsa_cipher = PKCS1_OAEP.new(rsa_key_pub)

    # create the key, encrypt it with rsa, and save to redis
    new_aes_key = get_random_bytes(16)
    aes_cipher = AES.new(new_aes_key, AES.MODE_EAX)
    encrypted_bin_aes_key = rsa_cipher.encrypt(new_aes_key)
    encrypted_aes_key = b64encode(encrypted_bin_aes_key)

    nonce = aes_cipher.nonce
    ciphertext, tag = aes_cipher.encrypt_and_digest(key.encode())
    key_cryptstuff = '#' + b64encode(encrypted_aes_key + b'|' + b64encode(nonce) + b'|' + b64encode(ciphertext) + b'|' + b64encode(tag)).decode('utf-8')

    conn = get_raw_conn()
    cursor = conn.cursor()
    model = {
        'service': service,
        'discord_channel_ids': discord_channel_ids,
        'encrypted_key': key_cryptstuff,
        'contributor_id': int(contributor_id) if contributor_id else None,
        'hash': hashlib.sha256((key + ENV_VARS.SALT).encode('utf-8')).hexdigest()
    }
    query = "INSERT INTO saved_session_keys_with_hashes ({fields}) VALUES ({values}) ON CONFLICT DO NOTHING".format(
        fields=','.join(model.keys()),
        values=','.join(['%s'] * len(model.values()))
    )
    cursor.execute(query, list(model.values()))
    conn.commit()
    return_conn(conn)
    if contributor_id:
        delete_keys(['saved_keys:' + str(contributor_id)])
