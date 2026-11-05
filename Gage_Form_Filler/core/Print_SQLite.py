"""Print the contents of an SQLite database to the terminal."""

from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path(
    r"\\entbackenc.mt.gov\DNRC_AquariusArchive\AQMetadata\Aquarius_Alarms\Gage_Form_Filler\db\uploaded_data.sqlite"
)


def get_table_names(conn: sqlite3.Connection) -> list[str]:
    """Return all user table names in the SQLite database.

    Args:
        conn: Open SQLite connection.

    Returns:
        A list of table names.
    """
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
        """
    ).fetchall()
    return [row[0] for row in rows]


def print_table(conn: sqlite3.Connection, table_name: str) -> None:
    """Print one table's schema header and all rows.

    Args:
        conn: Open SQLite connection.
        table_name: Name of the table to print.
    """
    cursor = conn.execute(f"SELECT * FROM {table_name}")
    column_names = [description[0] for description in cursor.description]
    rows = cursor.fetchall()

    print("=" * 120)
    print(f"TABLE: {table_name}")
    print(f"COLUMNS: {column_names}")
    print(f"ROW COUNT: {len(rows)}")
    print("-" * 120)

    if not rows:
        print("(no rows)")
        return

    for index, row in enumerate(rows, start=1):
        print(f"Row {index}: {row}")

    print()


def main() -> None:
    """Connect to the SQLite database and print all tables and rows."""
    print(f"Database path: {DB_PATH}")
    print(f"Database exists: {DB_PATH.exists()}")

    with sqlite3.connect(DB_PATH) as conn:
        table_names = get_table_names(conn)

        print(f"Tables found: {table_names}")
        print()

        if not table_names:
            print("No tables found in database.")
            return

        for table_name in table_names:
            print_table(conn, table_name)


if __name__ == "__main__":
    main()