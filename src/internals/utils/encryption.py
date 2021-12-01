import json
from base64 import b64decode, b64encode
from os import makedirs
from os.path import join

from configs.env_vars import ENV_VARS
from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA

base_dir = '/tmp/session_keys/'


def encrypt_and_log_session(import_id, service, key):
    try:
        makedirs(base_dir, exist_ok=True)
        data = {
            'import_id': import_id,
            'service': service,
            'key': key
        }
        to_encrypt = json.dumps(data)

        key_der = b64decode(ENV_VARS.PUBKEY.strip())
        key_pub = RSA.importKey(key_der)
        cipher = PKCS1_OAEP.new(key_pub)
        cipher_text = cipher.encrypt(to_encrypt.encode())

        filename = f'{service}-{import_id}'
        to_write = b64encode(cipher_text).decode('utf-8')

        with open(join(base_dir, filename), 'w') as f:
            f.write(to_write)
    except Exception as e:
        print(f'Error encrypting session data. Continuing with import: {e}')
