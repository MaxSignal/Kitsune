# @REVIEW: This module seems to be very specific to the importer logic.
# Seeing as no other importer has a `lib` equivalent,
# consider moving this one to the importer folder.
# Also provide type hints to all functions.
import hashlib
import time
from urllib.parse import urlparse
import requests
import json
import httpx

# Mostly ripped from https://github.com/Amenly/onlyfans-scraper.

# @REVIEW: `auth` argument in these functions is of quite specific shape,
# so you have to provide a TypedDict for it.


def get_cookies(auth):
    # @REVIEW: do not assign new keys to dict after its creation
    data = {}
    data['sess'] = auth['sess']
    data['auth_id'] = auth['auth_id']
    if auth['auth_uid_']:
        # @REVIEW: use `f''` string for interpolation
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
    # @REVIEW: use `dict()` constructor for dict literals.
    content = {
        'static_param': static_param,
        'format': fmt,
        'checksum_indexes': checksum_indexes,
        'checksum_constant': checksum_constant
    }

    time2 = str(round(time.time() * 1000))

    # @REVIEW: no reason to parse the same link twice
    path = urlparse(link).path
    query = urlparse(link).query
    path = path if not query else f"{path}?{query}"

    # @REVIEW: do not reassign function arguments
    static_param = content['static_param']

    # @REVIEW: no 1 letter variables
    a = [static_param, time2, path, headers['user-id']]
    msg = "\n".join(a)

    message = msg.encode("utf-8")
    hash_object = hashlib.sha1(message)
    sha_1_sign = hash_object.hexdigest()
    sha_1_b = sha_1_sign.encode("ascii")

    checksum_indexes = content['checksum_indexes']
    checksum_constant = content['checksum_constant']
    checksum = sum(sha_1_b[i] for i in checksum_indexes) + checksum_constant

    # @REVIEW: No `format()` with positional arguments.
    # Also it's not obvious what string is it even formatting.
    final_sign = content['format'].format(sha_1_sign, abs(checksum))

    headers.update(
        {
            'sign': final_sign,
            'time': time2
        }
    )
    return headers


###
# @REVIEW: this function should return a typed dict.
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
