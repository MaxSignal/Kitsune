"""
Add size and image hash columns to file table
"""

from yoyo import step

__depends__ = {'20211124_01_O8GOk-add-revisions-table'}

steps = [
    step(
        "ALTER TABLE files ADD COLUMN size int",
        "ALTER TABLE files DROP COLUMN size"
    ),
    step(
        "ALTER TABLE files ADD COLUMN ihash varchar",
        "ALTER TABLE files DROP COLUMN ihash"
    )
]
