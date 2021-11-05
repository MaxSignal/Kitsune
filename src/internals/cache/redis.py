import redis
import dateutil
import datetime
import copy
import ujson
import redis
from os import getenv
import config

pool = None

def init():
    global pool
    pool = redis.ConnectionPool(host=config.redis_host, port=config.redis_port, db=0)
    return pool

def init_mq():
    global mq_pool
    mq_pool = redis.ConnectionPool(host=config.redis_host, port=config.redis_port, db=1)
    return mq_pool

def get_redis():
    return redis.Redis(connection_pool=pool)

def get_mq_redis():
    return redis.Redis(connection_pool=mq_pool)

def delete_keys(keys, mq=False):
    conn = get_redis() if not mq else get_mq_redis()
    for key in keys:
        conn.delete(key)

def delete_keys_pattern(patterns, mq=False):
    redis = get_redis() if not mq else get_mq_redis()
    for pattern in patterns:
        for key in redis.keys(pattern):
            redis.delete(key)

def serialize_dict(data):
    to_serialize = {
        'dates': [],
        'data': {}
    }

    for key, value in data.items():
        if type(value) is datetime.datetime:
            to_serialize['dates'].append(key)
            to_serialize['data'][key] = value.isoformat()
        else:
            to_serialize['data'][key] = value

    return ujson.dumps(to_serialize)

def deserialize_dict(data):
    data = ujson.loads(data)
    to_return = {}
    for key, value in data['data'].items():
        if key in data['dates']:
            to_return[key] = dateutil.parser.parse(value)
        else:
            to_return[key] = value
    return to_return

def serialize_dict_list(data):
    data = copy.deepcopy(data)
    return ujson.dumps(list(map(lambda elem: serialize_dict(elem), data)))

def deserialize_dict_list(data):
    data = ujson.loads(data)
    to_return = list(map(lambda elem: deserialize_dict(elem), data))
    return to_return