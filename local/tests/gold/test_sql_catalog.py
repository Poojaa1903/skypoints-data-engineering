"""Every table the Snowflake scripts read is created by an earlier script.

This does not connect to Snowflake. It stops a script from naming a
table that the DDL never creates, which is what broke silver_load.sql.
"""

import re
from pathlib import Path

SQL_ROOT = Path(__file__).resolve().parents[3] / "snowflake"
CREATE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_]+\.[a-z_]+)",
    re.IGNORECASE,
)
REFERENCE = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-z_]+\.[a-z_]+)",
    re.IGNORECASE,
)


def test_every_referenced_table_is_created():
    created = set()
    referenced = []
    for path in sorted(SQL_ROOT.rglob("*.sql")):
        text = path.read_text(encoding="utf-8")
        created.update(name.lower() for name in CREATE.findall(text))
        for name in REFERENCE.findall(text):
            referenced.append((path.name, name.lower()))

    missing = [(path, name) for path, name in referenced if name not in created]
    assert missing == []
