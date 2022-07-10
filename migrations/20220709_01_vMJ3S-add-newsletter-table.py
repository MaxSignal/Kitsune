"""
add newsletter table
"""

from yoyo import step

__depends__ = {'20211212_02_LdfLH-change-type-of-size-column-in-file-table'}

steps = [
    step("""
        CREATE TABLE fantia_newsletters (
            id varchar not null,
            user_id varchar not null,
            content text not null,
            added timestamp not null default CURRENT_TIMESTAMP,
            published timestamp,
            PRIMARY KEY (id)
        );
    """, 'DROP TABLE fantia_newsletters;'),
    step(
        'CREATE INDEX fantia_newsletters_user_id_idx ON fantia_newsletters USING btree (user_id)',
        'DROP INDEX fantia_newsletters_user_id_idx'
    ),
    step(
        'CREATE INDEX fantia_newsletters_added_idx ON fantia_newsletters USING btree (added)',
        'DROP INDEX fantia_newsletters_added_idx'
    ),
    step(
        'CREATE INDEX fantia_newsletters_published_idx ON fantia_newsletters USING btree (published)',
        'DROP INDEX fantia_newsletters_published_idx'
    ),
]
