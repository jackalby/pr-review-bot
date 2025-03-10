#!/usr/bin/env python3

import os
import json
import requests
from typing import List, Dict, Any, Optional

from github import Github
from core.models import PRDetails


class GitHubClient:
    """Handles all interactions with GitHub API."""

    def __init__(self, github_token: str):
        """
        Initialize GitHub client with authentication token.

        Args:
            github_token: GitHub authentication token
        """
        self.github_token = github_token
        self.gh = Github(github_token)

    def get_pr_details(self) -> PRDetails:
        """
        Retrieves details of the pull request from GitHub Actions event payload.

        Returns:
            PRDetails object containing PR information
        """
        with open(os.environ["GITHUB_EVENT_PATH"], "r") as f:
            event_data = json.load(f)

        # Handle comment trigger differently from direct PR events
        if "issue" in event_data and "pull_request" in event_data["issue"]:
            # For comment triggers, we need to get the PR number from the issue
            pull_number = event_data["issue"]["number"]
            repo_full_name = event_data["repository"]["full_name"]
        else:
            # Original logic for direct PR events
            pull_number = event_data["number"]
            repo_full_name = event_data["repository"]["full_name"]

        owner, repo = repo_full_name.split("/")

        repo_obj = self.gh.get_repo(repo_full_name)
        pr = repo_obj.get_pull(pull_number)

        return PRDetails(owner, repo, pull_number, pr.title, pr.body)

    def get_diff(self, owner: str, repo: str, pull_number: int) -> str:
        """
        Fetches the diff of the pull request from GitHub API.

        Args:
            owner: Repository owner
            repo: Repository name
            pull_number: Pull request number

        Returns:
            String containing the diff
        """
        # Use the correct repository name format
        repo_name = f"{owner}/{repo}"
        print(f"Attempting to get diff for: {repo_name} PR#{pull_number}")

        repo_obj = self.gh.get_repo(repo_name)
        pr = repo_obj.get_pull(pull_number)

        # Use the GitHub API URL directly
        api_url = f"https://api.github.com/repos/{repo_name}/pulls/{pull_number}"

        headers = {
            'Authorization': f'Bearer {self.github_token}',
            'Accept': 'application/vnd.github.v3.diff'
        }

        response = requests.get(f"{api_url}.diff", headers=headers)

        if response.status_code == 200:
            diff = response.text
            print(f"Retrieved diff length: {len(diff) if diff else 0}")
            return diff
        else:
            print(f"Failed to get diff. Status code: {response.status_code}")
            print(f"Response content: {response.text}")
            print(f"URL attempted: {api_url}.diff")
            return ""

    def create_review_comment(
            self,
            owner: str,
            repo: str,
            pull_number: int,
            comments: List[Dict[str, Any]],
    ) -> None:
        """
        Submits the review comments to the GitHub API.

        Args:
            owner: Repository owner
            repo: Repository name
            pull_number: Pull request number
            comments: List of comments to create
        """
        print(f"Attempting to create {len(comments)} review comments")

        repo_obj = self.gh.get_repo(f"{owner}/{repo}")
        pr = repo_obj.get_pull(pull_number)
        try:
            # Create the review with only the required fields
            review = pr.create_review(
                body="Code Reviewer Comments",
                comments=comments,
                event="COMMENT"
            )
            print(f"Review created successfully with ID: {review.id}")

        except Exception as e:
            print(f"Error creating review: {str(e)}")
            print(f"Error type: {type(e)}")