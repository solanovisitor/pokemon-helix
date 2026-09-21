"""Optional compact HF views derived only from an already sanitized export."""
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import tempfile


def append_gallery(directory: Path, source_files: dict) -> dict:
    """Write bounded-memory Parquet views; retain every original public file.

    HF selects one builder for a repository's configs, so both gallery and full
    original_art views use Parquet. The original JSONL remains unchanged too.
    """
    try:
        from datasets import Features, Image, List, Value
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ValueError("Gallery export needs: uv run --with datasets==5.0.1 --with pillow==12.3.0 python scripts/export-adventure-dataset.py ... --gallery") from None
    from genetics.batches import DATASET_SCHEMA
    compact = Features({"image": Image(), "id": Value("string"), "generation": Value("int64"),
                        "parents": List(Value("string")), "description": Value("string")})
    complete = Features({name: List(Value("string")) if kind == "list[string]"
                         else Value("int64" if kind == "int64" else "string") for name, kind in DATASET_SCHEMA.items()})
    metadata = sorted(name for name in source_files if name.endswith("metadata.jsonl"))
    prefixes = {}
    for name in metadata:
        for line in (directory / name).read_bytes().splitlines():
            row = json.loads(line)
            for identity in [row["individual_id"], *row["parents"]]:
                if prefixes.setdefault(identity[:12], identity) != identity:
                    raise ValueError("Display ID prefixes collide; retain full IDs before creating a gallery")

    def rows(name, *, gallery):
        path = directory / name
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != source_files[name]["sha256"]:
            raise ValueError("Public metadata changed while creating the gallery")
        for line in raw.splitlines():
            row = json.loads(line)
            if not gallery:
                yield row
                continue
            image = (path.parent / row["file_name"]).read_bytes()
            if sha256(image).hexdigest() != row["source_sha256"]:
                raise ValueError("Public source image changed while creating the gallery")
            description = json.loads(row["expression_json"])["silhouette"]
            if not isinstance(description, str):
                raise ValueError("Existing silhouette description is required; labels are not invented")
            yield {"image": {"bytes": image, "path": row["file_name"]}, "id": row["individual_id"][:12],
                   "generation": row["generation"], "parents": [identity[:12] for identity in row["parents"]],
                   "description": description}

    files = {}
    for number, name in enumerate(metadata):
        for gallery, features, folder in ((True, compact, "gallery"), (False, complete, "original-art")):
            target = directory / folder / f"shard-{number:05d}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".parquet-", dir=target.parent, delete=False) as temporary:
                temp_path = Path(temporary.name)
            try:
                with pq.ParquetWriter(temp_path, features.arrow_schema, compression="zstd") as writer:
                    for row in rows(name, gallery=gallery):
                        writer.write_table(pa.Table.from_pylist([row], schema=features.arrow_schema))
                with temp_path.open("rb") as handle:
                    os.fsync(handle.fileno())
                    checksum = file_digest(handle, "sha256").hexdigest()
                try:
                    os.link(temp_path, target)  # Atomic no-replace, same filesystem.
                except FileExistsError:
                    with target.open("rb") as handle:
                        if file_digest(handle, "sha256").hexdigest() != checksum:
                            raise ValueError("A retained gallery differs; use a new export directory") from None
                files[target.relative_to(directory).as_posix()] = {"sha256": checksum, "bytes": target.stat().st_size}
            finally:
                temp_path.unlink(missing_ok=True)
    return files
