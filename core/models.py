#!/usr/bin/env python3

from dataclasses import dataclass
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


@dataclass
class PRDetails:
    """Data class for pull request details."""
    owner: str
    repo: str
    pull_number: int
    title: str
    description: Optional[str] = None


@dataclass
class FileChange:
    """Data class for a changed file in a PR."""
    path: str
    hunks: List[Dict[str, Any]]


class HunkReview(BaseModel):
    lineNumber: int = Field(..., description="The Line Number of the current code hunk")
    reviewComment: str = Field(..., description="The code review comment")
    priority: int = Field(2, description="Priority level: 1=critical (bugs, security), 2=improvement (quality, performance)")

class FileReviews(BaseModel):
    reviews: List[HunkReview] = Field(..., description="All code reviews")
