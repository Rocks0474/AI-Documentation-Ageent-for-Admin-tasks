"""Application settings — Pydantic, sourced from the environment.

A single ``Settings`` model reads every environment variable the system uses
(see ``.env.local`` / ``.env.gcp.example`` / ``.env.aws.example``). It is
cloud-agnostic: the GCP- and AWS-specific blocks are simply ignored when
``cloud_target`` is not that target (Constraint #6).

Use :func:`get_settings` for a cached, process-wide instance.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudTarget(str, Enum):
    LOCAL = "LOCAL"
    GCP = "GCP"
    AWS = "AWS"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required for all targets ---------------------------------------
    cloud_target: CloudTarget = CloudTarget.LOCAL
    anthropic_api_key: Optional[str] = None  # may be fetched via SecretsAdapter
    log_level: str = "INFO"

    # --- Agent configuration --------------------------------------------
    default_jurisdiction: str = "JP"
    default_output_language: str = "EN"
    minimum_cohort_size: int = 10  # Analytics Agent privacy floor

    # --- PII Gateway -----------------------------------------------------
    hris_system: str = "SMARTHR"  # WORKDAY | SAP | SMARTHR | BAMBOOHR
    hris_api_base_url: Optional[str] = None
    hris_api_key_secret: str = "hris-api-key"  # name in SecretsAdapter

    # --- Integrations (all optional; agents degrade gracefully) ---------
    greenhouse_connected: bool = False
    greenhouse_api_key_secret: str = "greenhouse-api-key"
    goodtime_connected: bool = False
    goodtime_api_key_secret: str = "goodtime-api-key"
    deel_connected: bool = False
    deel_api_key_secret: str = "deel-api-key"
    panalyt_connected: bool = False
    panalyt_api_key_secret: str = "panalyt-api-key"
    arize_connected: bool = False
    arize_api_key_secret: str = "arize-api-key"

    # --- GCP-specific (ignored if cloud_target != GCP) ------------------
    gcp_project_id: Optional[str] = None
    gcp_region: str = "asia-northeast1"  # Tokyo — default for JP clients
    gcs_bucket_zone2: Optional[str] = None
    gcs_bucket_zone3: Optional[str] = None
    gcs_bucket_audit: Optional[str] = None
    pubsub_topic_routing: Optional[str] = None
    vertex_index_id_zone2: Optional[str] = None
    vertex_index_id_zone3: Optional[str] = None

    # --- AWS-specific (ignored if cloud_target != AWS) ------------------
    aws_region: str = "ap-northeast-1"  # Tokyo — default for JP clients
    aws_account_id: Optional[str] = None
    s3_bucket_zone2: Optional[str] = None
    s3_bucket_zone3: Optional[str] = None
    s3_bucket_audit: Optional[str] = None
    sqs_queue_url_routing: Optional[str] = None
    opensearch_endpoint_zone2: Optional[str] = None
    opensearch_endpoint_zone3: Optional[str] = None

    # --- Local dev (ignored if cloud_target != LOCAL) -------------------
    local_storage_root: str = "./local_storage"
    local_secrets_file: str = "./secrets.local.json"


@lru_cache(maxsize=None)
def get_settings() -> Settings:
    """Return the cached, process-wide settings instance."""
    return Settings()
