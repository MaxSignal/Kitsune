import json
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP, AES
from Crypto.Random import get_random_bytes
from base64 import b64decode, b64encode
from os import makedirs
from os.path import join
import uuid
import config

base_dir = '/tmp/session_keys/'


def decrypt_session(file, rsa_key):
    key_der = b64decode(rsa_key.strip())
    key_prv = RSA.importKey(key_der)
    rsa_cipher = PKCS1_OAEP.new(key_prv)
    with open(file, 'r') as f:
        to_decrypt = f.read()
        encrypted_aes_key, nonce, ct, tag = (b64decode(x) for x in b64decode(to_decrypt).decode('utf-8').split('|'))
        decrypted_aes_key = rsa_cipher.decrypt(encrypted_aes_key)
        cipher = AES.new(decrypted_aes_key, AES.MODE_EAX, nonce)
        decrypted_session = cipher.decrypt_and_verify(ct, tag).decode('utf-8')
        return decrypted_session


def encrypt_and_log_session(import_id, service, key):
    try:
        makedirs(base_dir, exist_ok=True)
        data = {
            'import_id': import_id,
            'service': service,
            'key': key
        }
        to_encrypt = json.dumps(data)

        key_der = b64decode(config.pubkey.strip())
        key_pub = RSA.importKey(key_der)
        cipher = PKCS1_OAEP.new(key_pub)

        new_aes_key = get_random_bytes(16)
        aes_cipher = AES.new(new_aes_key, AES.MODE_EAX)
        encrypted_bin_aes_key = cipher.encrypt(new_aes_key)
        encrypted_aes_key = b64encode(encrypted_bin_aes_key)

        nonce = aes_cipher.nonce
        ciphertext, tag = aes_cipher.encrypt_and_digest(to_encrypt.encode())
        to_write = b64encode(encrypted_aes_key + b'|' + b64encode(nonce) + b'|' + b64encode(ciphertext) + b'|' + b64encode(tag)).decode('utf-8')

        filename = f'{service}-{import_id}'

        with open(join(base_dir, filename), 'w') as f:
            f.write(to_write)
    except Exception as e:
        print(f'Error encrypting session data. Continuing with import: {e}')
