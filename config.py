#!/usr/bin/env python3

import os
from typing import Dict, Any, List


def load_config() -> Dict[str, Any]:
    """
    Loads configuration from environment variables.

    Returns:
        Dict containing configuration values
    """
    # Parse exclude patterns
    exclude_patterns_raw = os.environ.get("INPUT_EXCLUDE", "")
    exclude_patterns = []
    if exclude_patterns_raw and exclude_patterns_raw.strip():
        exclude_patterns = [p.strip() for p in exclude_patterns_raw.split(",") if p.strip()]

    # Load Azure OpenAI config if enabled
    ai_review_enabled = os.environ.get("INPUT_AI_REVIEW_ENABLED", "true").lower() == "true"

    # Load which reviewers to run
    enabled_reviewers = os.environ.get("INPUT_ENABLED_REVIEWERS", "ai").split(",")
    enabled_reviewers = [r.strip() for r in enabled_reviewers if r.strip()]

    config = {
        # GitHub configuration
        "github_token": os.environ.get("GITHUB_TOKEN"),

        # General configuration
        "exclude_patterns": exclude_patterns,
        "enabled_reviewers": enabled_reviewers,

        # Azure OpenAI configuration
        "ai_review_enabled": ai_review_enabled,
        "azure_openai_endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT"),
        "azure_openai_key": os.environ.get("AZURE_OPENAI_KEY"),
        "azure_openai_deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
        "azure_openai_api_version": os.environ.get("AZURE_OPENAI_API_VERSION"),
    }

    return config