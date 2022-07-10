"""
rename newsletter tables
"""

from yoyo import step

__depends__ = {'20220709_01_vMJ3S-add-newsletter-table'}

steps = [
    step(
        'ALTER TABLE fantia_newsletters RENAME TO fanbox_newsletters',
        'ALTER TABLE fanbox_newsletters RENAME TO fantia_newsletters'
    ),
    step(
        'ALTER INDEX fantia_newsletters_user_id_idx RENAME TO fanbox_newsletters_user_id_idx',
        'ALTER INDEX fanbox_newsletters_user_id_idx RENAME TO fantia_newsletters_user_id_idx'
    ),
    step(
        'ALTER INDEX fantia_newsletters_added_idx RENAME TO fanbox_newsletters_added_idx',
        'ALTER INDEX fanbox_newsletters_added_idx RENAME TO fantia_newsletters_added_idx'
    ),
    step(
        'ALTER INDEX fantia_newsletters_published_idx RENAME TO fanbox_newsletters_published_idx',
        'ALTER INDEX fanbox_newsletters_published_idx RENAME TO fantia_newsletters_published_idx'
    )
]
