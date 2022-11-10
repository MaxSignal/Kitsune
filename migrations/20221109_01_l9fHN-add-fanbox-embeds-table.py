"""
Add fanbox_embeds table
"""

from yoyo import step

__depends__ = {'20220709_02_tUc0A-rename-newsletter-tables'}

steps = [
    step("""
        CREATE TABLE fanbox_embeds (
            id varchar not null,
            user_id varchar not null,
            post_id varchar not null,
            type varchar not null,
            json varchar not null,
            added timestamp not null default CURRENT_TIMESTAMP,
            processed boolean not null default false,
            PRIMARY KEY (id)
        );
    """, 'DROP TABLE fanbox_embeds;'),
    step(
        'CREATE INDEX fanbox_embeds_user_id_idx ON fanbox_embeds USING btree (user_id)',
        'DROP INDEX fanbox_embeds_user_id_idx'
    ),
    step(
        'CREATE INDEX fanbox_embeds_post_id_idx ON fanbox_embeds USING btree (post_id)',
        'DROP INDEX fanbox_embeds_post_id_idx'
    ),
    step(
        'CREATE INDEX fanbox_embeds_added_idx ON fanbox_embeds USING btree (added)',
        'DROP INDEX fanbox_embeds_added_idx'
    ),
    step(
        'CREATE INDEX fanbox_embeds_type_idx ON fanbox_embeds USING btree (type)',
        'DROP INDEX fanbox_embeds_type_idx'
    ),
]
