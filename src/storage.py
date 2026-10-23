"""MinIO object-storage integration.

Design decision (documented in README too): DuckDB in this project never
reads from MinIO directly over the network. Instead, this module uploads
local files to MinIO (as an auditable, versioned copy of raw/processed
data — the "object storage" layer the architecture calls for) and
downloads them back to a local path when something needs to read them.
DuckDB always queries the local file. This keeps the query path fast and
deterministic, and keeps the MinIO integration simple enough to debug.
"""
from __future__ import annotations

from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from src.utils import env, get_logger

logger = get_logger(__name__)


def get_client():
    endpoint = env("MINIO_ENDPOINT", "localhost:9000")
    use_ssl = env("MINIO_USE_SSL", "false").lower() == "true"
    scheme = "https" if use_ssl else "http"
    return boto3.client(
        "s3",
        endpoint_url=f"{scheme}://{endpoint}",
        aws_access_key_id=env("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=env("MINIO_ROOT_PASSWORD", "minioadmin123"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
        logger.info(f"Bucket already exists: {bucket}")
    except ClientError:
        client.create_bucket(Bucket=bucket)
        logger.info(f"Created bucket: {bucket}")


def upload_file(client, bucket: str, local_path: str | Path, object_name: str | None = None) -> str:
    local_path = Path(local_path)
    object_name = object_name or local_path.name
    ensure_bucket(client, bucket)
    client.upload_file(str(local_path), bucket, object_name)
    logger.info(f"Uploaded {local_path} -> s3://{bucket}/{object_name}")
    return object_name


def download_file(client, bucket: str, object_name: str, local_path: str | Path) -> Path:
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, object_name, str(local_path))
    logger.info(f"Downloaded s3://{bucket}/{object_name} -> {local_path}")
    return local_path


def object_exists(client, bucket: str, object_name: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=object_name)
        return True
    except ClientError:
        return False


def list_objects(client, bucket: str) -> list[str]:
    try:
        resp = client.list_objects_v2(Bucket=bucket)
    except ClientError:
        return []
    return [obj["Key"] for obj in resp.get("Contents", [])]
