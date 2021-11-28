import hashlib
import time
from urllib.parse import urlparse
import requests
import json
import httpx

# Mostly ripped from https://github.com/Amenly/onlyfans-scraper.


def get_cookies(auth):
    data = {}
    data['sess'] = auth['sess']
    data['auth_id'] = auth['auth_id']
    if auth['auth_uid_']:
        data['auth_uid_{}'.format(auth['auth_id'])] = auth['auth_uid_']
    return data


def make_headers(auth):
    headers = {
        'accept': 'application/json, text/plain, */*',
        'app-token': auth['app-token'],
        'user-id': auth['auth_id'],
        'x-bc': auth['x-bc'],
        'referer': 'https://onlyfans.com',
        'user-agent': auth['user_agent'],
    }
    return headers


def create_sign(link, headers):
    """
    credit: DC and hippothon
    https://raw.githubusercontent.com/DATAHOARDERS/dynamic-rules/main/onlyfans.json
    """

    (static_param, fmt, checksum_indexes, checksum_constant) = get_request_auth()
    content = {
        'static_param': static_param,
        'format': fmt,
        'checksum_indexes': checksum_indexes,
        'checksum_constant': checksum_constant
    }

    time2 = str(round(time.time() * 1000))

    path = urlparse(link).path
    query = urlparse(link).query
    path = path if not query else f"{path}?{query}"

    static_param = content['static_param']

    a = [static_param, time2, path, headers['user-id']]
    msg = "\n".join(a)

    message = msg.encode("utf-8")
    hash_object = hashlib.sha1(message)
    sha_1_sign = hash_object.hexdigest()
    sha_1_b = sha_1_sign.encode("ascii")

    checksum_indexes = content['checksum_indexes']
    checksum_constant = content['checksum_constant']
    checksum = sum(sha_1_b[i] for i in checksum_indexes) + checksum_constant

    final_sign = content['format'].format(sha_1_sign, abs(checksum))

    headers.update(
        {
            'sign': final_sign,
            'time': time2
        }
    )
    return headers


###
def get_request_auth():
    with httpx.Client(http2=True) as c:
        r = c.get('https://raw.githubusercontent.com/DATAHOARDERS/dynamic-rules/main/onlyfans.json')
    if not r.is_error:
        content = r.json()
        static_param = content['static_param']
        fmt = content['format']
        checksum_indexes = content['checksum_indexes']
        checksum_constant = content['checksum_constant']
        return (static_param, fmt, checksum_indexes, checksum_constant)
    else:
        return []
