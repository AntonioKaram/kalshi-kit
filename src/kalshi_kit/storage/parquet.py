from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd


class ParquetSink:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def append_records(self, table: str, records: Iterable[Mapping[str, object]]) -> None:
        rows = list(records)
        if not rows:
            return
        path = self.root / f"{table}.parquet"
        frame = pd.DataFrame([self._normalize(row) for row in rows])
        if path.exists():
            existing = pd.read_parquet(path)
            frame = pd.concat([existing, frame], ignore_index=True)
        frame.to_parquet(path, index=False)

    @staticmethod
    def _normalize(row: Mapping[str, object]) -> dict[str, object]:
        normalized: dict[str, object] = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                normalized[key] = json.dumps(value, default=str)
            else:
                normalized[key] = value
        return normalized
