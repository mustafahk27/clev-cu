"""Save/load Observations as JSON (gzipped when the path ends in .gz). Used for test fixtures."""

from __future__ import annotations

import gzip
from pathlib import Path

from clev.core.types import Observation


def save_observation(obs: Observation, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = obs.model_dump_json(indent=None).encode()
    path.write_bytes(gzip.compress(data, mtime=0) if path.suffix == ".gz" else data)


def load_observation(path: Path) -> Observation:
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    return Observation.model_validate_json(data)
