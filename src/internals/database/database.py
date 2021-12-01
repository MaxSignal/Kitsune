from flask import g
from psycopg2_pool import ThreadSafeConnectionPool
from psycopg2.extensions import make_dsn, connection
from psycopg2.extras import RealDictCursor

from configs.env_vars import ENV_VARS

pool: ThreadSafeConnectionPool = None


def init():
    global pool
    try:
        pool = ThreadSafeConnectionPool(
            minconn=0,
            maxconn=5000,
            idle_timeout=300,
            dsn=make_dsn(
                host=ENV_VARS.DATABASE_HOST,
                dbname=ENV_VARS.DATABASE_DBNAME,
                user=ENV_VARS.DATABASE_USER,
                password=ENV_VARS.DATABASE_PASSWORD,
                port=5432
            )
        )
    except Exception as e:
        print(f'Failed to connect to the database: {e}')
    return pool


def get_pool():
    global pool
    return pool


def get_cursor():
    if 'cursor' not in g:
        g.connection = get_conn()
        g.cursor = g.connection.cursor()
    return g.cursor


def get_raw_conn() -> connection:
    conn = pool.getconn()
    conn.cursor_factory = RealDictCursor
    return conn


def get_conn():
    if 'connection' not in g:
        g.connection = pool.getconn()
        g.connection.cursor_factory = RealDictCursor
    return g.connection


def return_conn(conn):
    if conn is not None:
        pool.putconn(conn)
