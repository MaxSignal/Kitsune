"""
Fix fanbox_embeds processed column
"""

from yoyo import step

__depends__ = {'20221109_01_l9fHN-add-fanbox-embeds-table'}

steps = [
    step(
        'ALTER TABLE fanbox_embeds DROP COLUMN processed',
        'ALTER TABLE fanbox_embeds ADD COLUMN processed boolean not null default false'
    ),
    step(
        'ALTER TABLE fanbox_embeds ADD COLUMN processed varchar',
        'ALTER TABLE fanbox_embeds DROP COLUMN processed'
    ),
]
