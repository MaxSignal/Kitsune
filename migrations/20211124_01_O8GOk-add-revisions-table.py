"""
Add revisions table
"""

from yoyo import step

__depends__ = {'20211028_01_k4D9Q-add-indexes-to-flag-table'}

steps = [
    step("""
        CREATE TABLE revisions (
            "revision_id" SERIAL PRIMARY KEY,
            "id" varchar(255) NOT NULL,
            "user" varchar(255) NOT NULL,
            "service" varchar(20) NOT NULL,
            "title" text NOT NULL DEFAULT '',
            "content" text NOT NULL DEFAULT '',
            "embed" jsonb NOT NULL DEFAULT '{}',
            "shared_file" boolean NOT NULL DEFAULT '0',
            "added" timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "published" timestamp,
            "edited" timestamp,
            "file" jsonb NOT NULL,
            "attachments" jsonb[] NOT NULL
        );
    """, 'DROP TABLE revisions')
]
