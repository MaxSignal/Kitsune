"""
Change type of size column in file table
"""

from yoyo import step

__depends__ = {'20211212_01_K1PlV-add-size-and-image-hash-columns-to-file-table'}

steps = [
    step(
        "ALTER TABLE files ALTER COLUMN size TYPE bigint",
        "ALTER TABLE files ALTER COLUMN size TYPE int"
    )
]
