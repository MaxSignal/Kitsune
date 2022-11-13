"""
Add fancards table
"""

from yoyo import step

__depends__ = {'20221111_01_jQjnV-add-processed-json-column-to-fanbox-embeds'}

steps = [
    step("""
        CREATE TABLE fanbox_fancards (
            id serial primary key,
            user_id varchar not null,
            file_id int not null references files(id),
            UNIQUE (user_id, file_id)
        );
    """),
    step(
        'CREATE INDEX fanbox_fancards_user_id_idx ON fanbox_fancards USING btree (user_id)',
        'DROP INDEX fanbox_fancards_user_id_idx'
    ),
]
