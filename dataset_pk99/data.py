"""Read-only SQL extraction and explicit local cache, separate from the EDA."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import mysql.connector
import pandas as pd


QUERIES = {
    "accounts": "SELECT account_id, date AS opened_at FROM account ORDER BY account_id",
    "owners": """SELECT account_id, client_id FROM disp
                 WHERE type = 'OWNER' ORDER BY account_id""",
    "transactions": """SELECT trans_id, account_id, date AS trans_date,
                            type, operation, k_symbol
                       FROM trans ORDER BY account_id, date, trans_id""",
}
CACHE_VERSION = 1


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_tables(source: str, cache_dir: Path) -> tuple[dict, dict]:
    """Never fall back silently to old data; cache mode verifies file hashes."""
    if source == "cache":
        manifest = json.loads((cache_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest["cache_version"] != CACHE_VERSION or manifest["queries"] != QUERIES:
            raise ValueError("Cache incompatível; refaça a extração do banco.")
        tables = {}
        for name in QUERIES:
            path = cache_dir / f"{name}.csv.gz"
            if file_hash(path) != manifest["sha256"][name]:
                raise ValueError(f"Cache alterado ou incompleto: {path}")
            tables[name] = pd.read_csv(path, keep_default_na=False)
        return tables, manifest

    settings = {
        "host": os.getenv("BERKA_DB_HOST", "relational.fel.cvut.cz"),
        "port": int(os.getenv("BERKA_DB_PORT", "3306")),
        "user": os.getenv("BERKA_DB_USER", "guest"),
        # Public read-only credentials published by the CTU repository.
        "password": os.getenv("BERKA_DB_PASSWORD", "ctu-relational"),
        "database": os.getenv("BERKA_DB_NAME", "financial"),
        "connection_timeout": 20,
    }
    tables = {}
    try:
        with closing(mysql.connector.connect(**settings)) as connection:
            with closing(connection.cursor()) as cursor:
                for name, query in QUERIES.items():
                    print(f"Extraindo {name}...", flush=True)
                    cursor.execute(query)
                    tables[name] = pd.DataFrame.from_records(
                        cursor.fetchall(), columns=cursor.column_names
                    )
    except mysql.connector.Error as error:
        raise OSError(
            "Falha na consulta MySQL. Verifique conexão e BERKA_DB_*; "
            "se houver uma extração anterior completa, use --source cache. "
            f"Código do conector: {error.errno}."
        ) from error
    cache_dir.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, frame in tables.items():
        path = cache_dir / f"{name}.csv.gz"
        frame.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
        hashes[name] = file_hash(path)
    manifest = {
        "cache_version": CACHE_VERSION,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": settings["host"], "database": settings["database"],
        "queries": QUERIES,
        "rows": {name: len(frame) for name, frame in tables.items()},
        "sha256": hashes,
    }
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return tables, manifest
