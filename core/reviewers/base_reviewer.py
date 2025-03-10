#!/usr/bin/env python3

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from core.models import PRDetails


class BaseReviewer(ABC):
    """
    Base class for all code reviewers.
    Each reviewer should implement the review_file method.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = self.__class__.__name__

    def can_review_file(self, file_path: str) -> bool:
        """
        Determine if this reviewer can handle this file type.
        Can be overridden by subclasses for specific file type filtering.

        Args:
            file_path: Path to the file in the repository

        Returns:
            True if this reviewer can review the file, False otherwise
        """
        # Check exclude patterns by default
        exclude_patterns = self.config.get("exclude_patterns", [])
        import fnmatch
        should_exclude = any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude_patterns)
        return not should_exclude

    @abstractmethod
    def review_file(self, file_path: str, hunks: List[Dict[str, Any]], pr_details: PRDetails) -> List[Dict[str, Any]]:
        """
        Review a file and return comments.

        Args:
            file_path: Path to the file in the repository
            hunks: List of hunks from the diff
            pr_details: Pull request details

        Returns:
            List of comments, each with body, path, and position fields
        """
        pass