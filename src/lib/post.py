import os
import shutil
import tempfile
import json
from os import makedirs
from src.utils.utils import hash_dict
from src.internals.cache.redis import delete_keys
from src.internals.database.database import get_cursor, get_conn, return_conn, get_raw_conn
from shutil import rmtree
from os.path import join, exists
import config


def delete_post_cache_keys(service, artist_id, post_id):
    keys = [
        'post:' + service + ':' + str(artist_id) + ':' + str(post_id)
    ]

    delete_keys(keys)


def delete_all_post_cache_keys():
    keys = ['all_post_keys']

    delete_keys(keys)


def handle_post_import(post_model: dict):
    """
    Handles revision backups before proceeding with overwrite.
    """
    service = post_model['service']
    artist_id = post_model['"user"']
    post_id = post_model['id']
    existing_post = get_post(service, artist_id, post_id)
    if existing_post and hash_dict(post_model) != hash_dict(existing_post):
        # backup to `revisions`
        write_post_to_db(existing_post, table='revisions')
    write_post_to_db(post_model, table='posts')


def write_post_to_db(post_model: dict, table='posts'):
    post_model['embed'] = json.dumps(post_model['embed'])
    post_model['file'] = json.dumps(post_model['file'])
    for i in range(len(post_model['attachments'])):
        post_model['attachments'][i] = json.dumps(post_model['attachments'][i])

    columns = post_model.keys()
    data = ['%s'] * len(post_model.values())
    data[-1] = '%s::jsonb[]'  # attachments
    query = """
        INSERT INTO {table} ({fields}) VALUES ({values})
        ON CONFLICT (id, service)
        DO UPDATE SET {updates}
    """.format(
        table=table,
        fields=','.join(columns),
        values=','.join(data),
        updates=','.join([f'{column}=EXCLUDED.{column}' for column in columns])
    )
    conn = get_raw_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(query, list(post_model.values()))
        conn.commit()
    finally:
        return_conn(conn)


def get_post(service, artist_id, post_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM posts WHERE id = %s AND \"user\" = %s AND service = %s", (post_id, artist_id, service,))
    existing_post = cursor.fetchone()
    cursor.close()
    return_conn(conn)
    return existing_post


def post_exists(service, artist_id, post_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM posts WHERE id = %s AND \"user\" = %s AND service = %s", (post_id, artist_id, service,))
    existing_posts = cursor.fetchall()
    cursor.close()
    return_conn(conn)
    return len(existing_posts) > 0


def get_comment_ids_for_user(service, user_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM comments WHERE post_id IN (SELECT id FROM posts WHERE \"user\" = %s AND service = %s)", (user_id, service))
    existing_comment_ids = cursor.fetchall()
    cursor.close()
    return_conn(conn)
    return existing_comment_ids


def get_comments_for_posts(service, post_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM comments WHERE post_id = %s AND service = %s", (post_id, service))
    existing_posts = cursor.fetchall()
    cursor.close()
    return_conn(conn)
    return existing_posts


def comment_exists(service, commenter_id, comment_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM comments WHERE id = %s AND commenter = %s AND service = %s", (comment_id, commenter_id, service,))
    existing_posts = cursor.fetchall()
    cursor.close()
    return_conn(conn)
    return len(existing_posts) > 0


def post_flagged(service, artist_id, post_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM booru_flags WHERE service = %s AND "user" = %s AND id = %s', (service, artist_id, post_id))
    existing_flags = cursor.fetchall()
    cursor.close()
    return_conn(conn)
    return len(existing_flags) > 0


def discord_post_exists(server_id, channel_id, post_id):
    conn = get_raw_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM discord_posts WHERE id = %s AND server = %s AND channel = %s", (post_id, server_id, channel_id))
    existing_posts = cursor.fetchall()
    cursor.close()
    return_conn(conn)
    return len(existing_posts) > 0


def delete_post_flags(service, artist_id, post_id):
    conn = get_raw_conn()
    try:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM booru_flags WHERE service = %s AND "user" = %s AND id = %s', (service, artist_id, post_id))
        cursor.close()
        conn.commit()
    finally:
        return_conn(conn)


def get_base_paths(service_name, user_id, post_id):
    if service_name == 'patreon':
        return {'file': f"files/{user_id}/{post_id}", 'attachments': f"attachments/{user_id}/{post_id}"}
    elif service_name == 'gumroad':
        return {'file': f"files/gumroad/{user_id}/{post_id}", 'attachments': f"attachments/gumroad/{user_id}/{post_id}"}
    elif service_name == 'subscribestar':
        return {'file': f"files/subscribestar/{user_id}/{post_id}", 'attachments': f"attachments/subscribestar/{user_id}/{post_id}"}
    elif service_name == 'fanbox':
        return {'file': f"files/fanbox/{user_id}/{post_id}", 'attachments': f"attachments/fanbox/{user_id}/{post_id}"}
    elif service_name == 'fantia':
        return {'file': f"files/fantia/{user_id}/{post_id}", 'attachments': f"attachments/fantia/{user_id}/{post_id}"}


# TODO: Solve a possible race condition: thread A created dir, but thread B moved it afterwards
def move_to_backup(service_name, user_id, post_id):
    base_paths = get_base_paths(service_name, user_id, post_id)
    backup_path = tempfile.mkdtemp()
    if exists(join(config.download_path, base_paths['file'])):
        shutil.move(join(config.download_path, base_paths['file']), join(backup_path, 'file'))
    if exists(join(config.download_path, base_paths['attachments'])):
        shutil.move(join(config.download_path, base_paths['attachments']), join(backup_path, 'attachments'))
    return backup_path


def delete_backup(backup_path):
    shutil.rmtree(backup_path, ignore_errors=True)


def restore_from_backup(service_name, user_id, post_id, backup_path):
    base_paths = get_base_paths(service_name, user_id, post_id)
    shutil.rmtree(join(config.download_path, base_paths['file']), ignore_errors=True)
    if exists(join(backup_path, 'file')):
        os.rename(join(backup_path, 'file'), join(config.download_path, base_paths['file']))
    shutil.rmtree(join(config.download_path, base_paths['attachments']), ignore_errors=True)
    if exists(join(backup_path, 'attachments')):
        os.rename(join(backup_path, 'attachments'), join(config.download_path, base_paths['attachments']))
