#!/usr/bin/env python3

import os
import json
import fnmatch
from typing import List, Dict, Any

import requests
from github import Github
from pydantic import BaseModel, Field
from openai import AzureOpenAI
from unidiff.patch import Hunk

# GitHub authentication
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

# Initialize GitHub client
gh = Github(GITHUB_TOKEN)

# Azure OpenAI configuration
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_KEY = os.environ.get("AZURE_OPENAI_KEY")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION")


class HunkReview(BaseModel):
    lineNumber: int = Field(..., description="The Line Number of the current code hunk")
    reviewComment: str = Field(..., description="The code review comment")


class FileReviews(BaseModel):
    reviews: List[HunkReview] = Field(..., description="All code reviews")


class PRDetails:
    def __init__(self, owner: str, repo: str, pull_number: int, title: str, description: str):
        self.owner = owner
        self.repo = repo
        self.pull_number = pull_number
        self.title = title
        self.description = description


def get_pr_details() -> PRDetails:
    """Retrieves details of the pull request from GitHub Actions event payload."""
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

    repo = gh.get_repo(repo_full_name)
    pr = repo.get_pull(pull_number)

    return PRDetails(owner, repo.name, pull_number, pr.title, pr.body)


def get_diff(owner: str, repo: str, pull_number: int) -> str:
    """Fetches the diff of the pull request from GitHub API."""
    # Use the correct repository name format
    repo_name = f"{owner}/{repo}"
    print(f"Attempting to get diff for: {repo_name} PR#{pull_number}")

    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pull_number)

    # Use the GitHub API URL directly
    api_url = f"https://api.github.com/repos/{repo_name}/pulls/{pull_number}"

    headers = {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
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


def create_prompt(file_path, hunk, pr_title, pr_description) -> str:
    """Creates the prompt for the Azure OpenAI model."""
    return f"""Your task is reviewing pull requests. Instructions:
    - Provide the response in following JSON format:  {{"reviews": [{{"lineNumber":  <line_number>, "reviewComment": "<review comment>"}}]}}
    - Provide comments and suggestions ONLY if there is something to improve, otherwise "reviews" should be an empty array.
    - Use GitHub Markdown in comments
    - Focus on bugs, security issues, and performance problems
    - IMPORTANT: NEVER suggest adding comments to the code

Review the following code diff in the file "{file_path}" and take the pull request title and description into account when writing the response.

Pull request title: {pr_title}

Pull request description: 
---
{pr_description or 'No description provided'}
---

Git diff to review:
```diff
{hunk.content}
```
"""


def get_openai_review(prompt: str):
    """
    Sends a code review prompt to Azure OpenAI and returns the parsed reviews.

    Args:
        prompt (str): The prompt containing the code diff and review instructions

    Returns:
        List[Dict[str, str]]: A list of review comments with lineNumber and reviewComment
    """
    # Initialize the Azure OpenAI client
    client = AzureOpenAI(
        base_url=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_KEY,
        api_version=AZURE_OPENAI_API_VERSION
    )

    messages = [
        {
            "role": "system",
            "content": "You are an expert code reviewer. Provide specific, actionable feedback that helps improve code quality."
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    print("Sending request to Azure OpenAI...")

    try:
        # Try to use the beta.chat.completions.parse method if available
        try:
            response = client.beta.chat.completions.parse(
                model=AZURE_OPENAI_DEPLOYMENT,
                response_format=FileReviews,
                timeout=30,
                messages=messages)

            # Get the parsed structured output directly
            return {"reviews": response.choices[0].message.parsed.reviews}

        except (AttributeError, ImportError):
            # Fall back to regular chat completions with JSON mode
            print("Falling back to regular JSON mode...")
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                temperature=0.7,
                max_tokens=4000,
                response_format={"type": "json_object"},
                top_p=0.95
            )

            output = response.choices[0].message.content
            return json.loads(output)

    except Exception as e:
        print(f"Error during Azure OpenAI API call: {e}")
        return {"reviews": []}


def parse_diff(diff_str: str) -> List[Dict[str, Any]]:
    """Parses the diff string and returns a structured format."""
    files = []
    current_file = None
    current_hunk = None

    for line in diff_str.splitlines():
        if line.startswith('diff --git'):
            if current_file:
                files.append(current_file)
            current_file = {'path': '', 'hunks': []}

        elif line.startswith('--- a/'):
            if current_file:
                current_file['path'] = line[6:]

        elif line.startswith('+++ b/'):
            if current_file:
                current_file['path'] = line[6:]

        elif line.startswith('@@'):
            if current_file:
                current_hunk = {'header': line, 'lines': []}
                current_file['hunks'].append(current_hunk)

        elif current_hunk is not None:
            current_hunk['lines'].append(line)

    if current_file:
        files.append(current_file)

    return files


def create_comment(file_path, hunk: Hunk, reviews: Dict[str, List]) -> List[Dict[str, Any]]:
    """Creates comment objects from AI responses."""
    print(f"Processing reviews for file: {file_path}")
    print(f"Hunk details - start: {hunk.source_start}, length: {hunk.source_length}")

    comments = []
    for review in reviews.get('reviews', []):
        try:
            line_number = int(review["lineNumber"])
            print(f"AI suggested line: {line_number}")

            # Ensure the line number is within the hunk's range
            if line_number < 1 or line_number > hunk.source_length:
                print(f"Warning: Line number {line_number} is outside hunk range")
                continue

            comment = {
                "body": review["reviewComment"],
                "path": file_path,
                "position": line_number
            }
            print(f"Created comment for line {line_number}")
            comments.append(comment)

        except (KeyError, TypeError, ValueError) as e:
            print(f"Error creating comment from AI response: {e}, Response: {review}")

    return comments


def analyze_code(parsed_diff: List[Dict[str, Any]], pr_details: PRDetails) -> List[Dict[str, Any]]:
    """Analyzes the code changes using Azure OpenAI and generates review comments."""
    print("Starting code analysis...")
    print(f"Number of files to analyze: {len(parsed_diff)}")
    comments = []

    # Get and clean exclude patterns, handle empty input
    exclude_patterns_raw = os.environ.get("INPUT_EXCLUDE", "")
    print(f"Raw exclude patterns: {exclude_patterns_raw}")

    # Only split if we have a non-empty string
    exclude_patterns = []
    if exclude_patterns_raw and exclude_patterns_raw.strip():
        exclude_patterns = [p.strip() for p in exclude_patterns_raw.split(",") if p.strip()]
    print(f"Exclude patterns: {exclude_patterns}")

    # Process each file in the diff
    for file_data in parsed_diff:
        file_path = file_data.get('path', '')
        print(f"\nProcessing file: {file_path}")

        if not file_path or file_path == "/dev/null":
            continue

        # Check if file should be excluded
        should_exclude = any(fnmatch.fnmatch(file_path, pattern) for pattern in exclude_patterns)
        if should_exclude:
            print(f"Excluding file: {file_path}")
            continue

        hunks = file_data.get('hunks', [])
        print(f"Hunks in file: {len(hunks)}")

        for hunk_data in hunks:
            hunk_lines = hunk_data.get('lines', [])
            print(f"Number of lines in hunk: {len(hunk_lines)}")

            if not hunk_lines:
                continue

            hunk = Hunk()
            hunk.source_start = 1
            hunk.source_length = len(hunk_lines)
            hunk.target_start = 1
            hunk.target_length = len(hunk_lines)
            hunk.content = '\n'.join(hunk_lines)

            prompt = create_prompt(file_path, hunk, pr_details.title, pr_details.description)
            reviews = get_openai_review(prompt)
            print(f"Reviews received: {len(reviews.get('reviews', []))} items")

            if reviews and reviews.get('reviews'):
                new_comments = create_comment(file_path, hunk, reviews)
                if new_comments:
                    comments.extend(new_comments)

    print(f"Final comments list: {len(comments)} items")
    return comments


def create_review_comment(
        owner: str,
        repo: str,
        pull_number: int,
        comments: List[Dict[str, Any]],
):
    """Submits the review comments to the GitHub API."""
    print(f"Attempting to create {len(comments)} review comments")

    repo = gh.get_repo(f"{owner}/{repo}")
    pr = repo.get_pull(pull_number)
    try:
        # Create the review with only the required fields
        review = pr.create_review(
            body="AI Code Reviewer Comments",
            comments=comments,
            event="COMMENT"
        )
        print(f"Review created successfully with ID: {review.id}")

    except Exception as e:
        print(f"Error creating review: {str(e)}")
        print(f"Error type: {type(e)}")


def main():
    """Main function to execute the code review process."""
    print("Starting PR review bot...")

    # Validate environment variables
    required_vars = ["GITHUB_TOKEN", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY", "AZURE_OPENAI_DEPLOYMENT"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]

    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        return

    try:
        # Get PR details from GitHub Actions event
        pr_details = get_pr_details()
        print(f"Analyzing PR #{pr_details.pull_number} in repo {pr_details.owner}/{pr_details.repo}")

        # Get the diff
        diff = get_diff(pr_details.owner, pr_details.repo, pr_details.pull_number)
        if not diff:
            print("No diff found. Exiting.")
            return

        # Parse the diff
        parsed_diff = parse_diff(diff)

        # Analyze the code
        comments = analyze_code(parsed_diff, pr_details)

        # Create review comments if we have any
        if comments:
            create_review_comment(
                pr_details.owner, pr_details.repo, pr_details.pull_number, comments
            )
        else:
            print("No issues found to comment on. Great job!")

    except Exception as e:
        print(f"Error in main execution: {str(e)}")


if __name__ == "__main__":
    main()