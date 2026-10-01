"""Mind2Web step data (osunlp/Multimodal-Mind2Web test splits) mapped to Clev's inputs.

Only the needed parquet columns are read over HTTP (screenshots are ~95% of each file and are
skipped), then cached under evals/data/mind2web/.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

DATASET = "datasets/osunlp/Multimodal-Mind2Web/data"
# First shard of each official test split (~270 steps each): task, website and domain transfer.
SHARDS = {
    "test_task": "test_task-00000-of-00005-431389419142b606.parquet",
    "test_website": "test_website-00000-of-00004-e0bfff7049abbef8.parquet",
    "test_domain": "test_domain-00000-of-00011-{suffix}.parquet",
}
# Training-split shards used as a dev set for tuning. Never tune on the test splits above.
DEV_SHARDS = {
    "train_0": "train-00000-of-00027-4d11798d7219186d.parquet",
    "train_1": "train-00001-of-00027-2011d8e72a165f62.parquet",
}
COLUMNS = [
    "action_uid",
    "cleaned_html",
    "operation",
    "pos_candidates",
    "website",
    "domain",
    "annotation_id",
    "confirmed_task",
    "action_reprs",
    "target_action_index",
]
CACHE = Path("evals/data/mind2web")
_REPR = re.compile(r"^\[[^\]]*\]\s+(.*?)\s+->")


@dataclass
class Step:
    action_uid: str
    split: str
    website: str
    domain: str
    task: str
    html: str
    op: str  # CLICK | TYPE | SELECT | HOVER
    value: str
    target_ids: list[str]  # backend_node_ids of correct elements (may be empty: pruned)
    previous: list[str]  # action_reprs before this step

    @property
    def last_target(self) -> str | None:
        """Name of the element the previous action touched: '[textbox]  Zip -> TYPE: 1' -> 'Zip'."""
        if not self.previous:
            return None
        m = _REPR.match(self.previous[-1])
        return m.group(1).strip() if m else None

    @property
    def history(self) -> list[str]:
        """Previous actions as sentences, the way live Clev's done-list reads."""
        return [repr_to_sentence(r) for r in self.previous]

    @property
    def expected_verb(self) -> str:
        return "type" if self.op == "TYPE" else "click"


def _shard_path(split: str) -> str:
    name = SHARDS.get(split) or DEV_SHARDS[split]
    if "{suffix}" in name:  # resolve the hashed file name once
        from huggingface_hub import HfFileSystem

        prefix = name.split("{suffix}")[0]
        matches = [p for p in HfFileSystem().ls(DATASET, detail=False) if prefix in p]
        return sorted(matches)[0]
    return f"{DATASET}/{name}"


def _download(split: str) -> Path:
    """Fetch the needed columns of one shard, cached as a small local parquet file."""
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem

    out = CACHE / f"{split}.parquet"
    if out.exists():
        return out
    CACHE.mkdir(parents=True, exist_ok=True)
    with HfFileSystem().open(_shard_path(split), "rb") as f:
        table = pq.ParquetFile(f).read(columns=COLUMNS)
    pq.write_table(table, out)
    return out


def parse_row(row: dict, split: str) -> Step:
    op = json.loads(row["operation"])
    targets = [json.loads(c)["backend_node_id"] for c in row["pos_candidates"]]
    index = int(row["target_action_index"])
    return Step(
        action_uid=row["action_uid"],
        split=split,
        website=row["website"],
        domain=row["domain"],
        task=row["confirmed_task"],
        html=row["cleaned_html"],
        op=op["op"],
        value=op.get("value", ""),
        target_ids=targets,
        previous=list(row["action_reprs"][:index]),
    )


def load_steps(n: int, seed: int = 0, splits: tuple[str, ...] = tuple(SHARDS)) -> list[Step]:
    """`n` steps sampled evenly across the test splits, reproducibly."""
    import pyarrow.parquet as pq

    per_split = -(-n // len(splits))
    steps: list[Step] = []
    for split in splits:
        rows = pq.read_table(_download(split)).to_pylist()
        rng = random.Random(f"{seed}-{split}")
        rng.shuffle(rows)
        steps += [parse_row(r, split) for r in rows[:per_split]]
    random.Random(seed).shuffle(steps)
    return steps[:n]


def load_dev_steps(n: int, seed: int = 0) -> list[Step]:
    """`n` steps from the training split, for tuning (see DEV_SHARDS)."""
    return load_steps(n, seed, splits=tuple(DEV_SHARDS))


_FULL_REPR = re.compile(
    r"^\[(?P<tag>[^\]]*)\]\s+(?P<name>.*?)\s+->\s+(?P<op>\w+)(?::\s*(?P<value>.*))?$"
)


def repr_to_sentence(r: str) -> str:
    """'[textbox]  Zip -> TYPE: 08817' -> 'Typed "08817" into textbox "Zip"'."""
    m = _FULL_REPR.match(r.strip())
    if not m:
        return r
    tag, name, op, value = m["tag"], m["name"].strip(), m["op"], (m["value"] or "").strip()
    what = f'{tag} "{name}"' if name else tag
    match op:
        case "TYPE":
            return f'Typed "{value}" into {what}'
        case "SELECT":
            return f'Selected "{value}" in {what}'
        case "HOVER":
            return f"Hovered over {what}"
        case _:
            return f"Clicked {what}"
