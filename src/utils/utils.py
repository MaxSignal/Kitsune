import json
import datetime
import ujson


def _serialize_model_for_hashing(data):
    to_serialize = {
        'dates': [],
        'data': {}
    }

    data.pop('added', None)  # This field will throw off hashing, so discard.

    for key, value in data.items():
        if type(value) is datetime.datetime:
            to_serialize['dates'].append(key)
            to_serialize['data'][key] = value.isoformat()
        else:
            to_serialize['data'][key] = value

    return ujson.dumps(to_serialize, sort_keys=True)


def hash_post(_dict: dict):
    return _serialize_model_for_hashing(_dict)
