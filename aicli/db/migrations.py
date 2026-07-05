"""
Schema migration registry.

To add a migration:
  1. Write a function  def migrate_vN(conn): ...  that runs ALTER TABLE / etc.
  2. Append it to MIGRATIONS.
  3. SCHEMA_VERSION increments automatically (len(MIGRATIONS)).

Rules: migrations are additive only — ADD COLUMN with a default, new tables.
Never rename columns or change types; that loses data.
"""

import sqlite3


def _migrate_v0(conn: sqlite3.Connection) -> None:
    # ponytail: no-op — v0→v1 just stamps the version on existing installs
    pass


MIGRATIONS: list = [_migrate_v0]

SCHEMA_VERSION: int = len(MIGRATIONS)  # currently 1
