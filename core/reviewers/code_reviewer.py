#!/usr/bin/env python3

import json
from typing import List, Dict, Any, Optional

from openai import AzureOpenAI
from unidiff.patch import Hunk

from core.models import PRDetails, FileReviews
from core.reviewers.base_reviewer import BaseReviewer



class AICodeReviewer(BaseReviewer):
    """AI-powered code reviewer using Azure OpenAI."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Initialize the Azure OpenAI client
        self.client = AzureOpenAI(
            base_url=config.get("azure_openai_endpoint"),
            api_key=config.get("azure_openai_key"),
            api_version=config.get("azure_openai_api_version")
        )
        self.deployment = config.get("azure_openai_deployment")

    def review_file(self, file_path: str, hunks: List[Dict[str, Any]], pr_details: PRDetails) -> List[Dict[str, Any]]:
        """
        Review a file using AI and return comments.

        Args:
            file_path: Path to the file in the repository
            hunks: List of hunks from the diff
            pr_details: Pull request details

        Returns:
            List of comments, each with body, path, and position fields
        """
        comments = []

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

            prompt = self._create_prompt(file_path, hunk, pr_details.title, pr_details.description)
            reviews = self._get_openai_review(prompt)
            print(f"Reviews received: {len(reviews.get('reviews', []))} items")

            if reviews and reviews.get('reviews'):
                new_comments = self._create_comment(file_path, hunk, reviews)
                if new_comments:
                    comments.extend(new_comments)

        return comments

    def _create_prompt(self, file_path: str, hunk: Hunk, pr_title: str, pr_description: Optional[str]) -> str:
        """
        Creates the prompt for the Azure OpenAI model.

        Args:
            file_path: Path to the file in the repository
            hunk: Hunk from the diff
            pr_title: Pull request title
            pr_description: Pull request description

        Returns:
            Prompt string for OpenAI
        """
        return f"""Your task is to review the following pull request.
        Instructions:
        - Provide the response in following JSON format:  {{"reviews": [{{"lineNumber":  <line_number>, "reviewComment": "<review comment>"}}]}}
        - Provide comments and suggestions ONLY if there is something to improve, otherwise "reviews" should be an empty array.
        - Use GitHub Markdown in comments
        - Focus on bugs, security issues, and performance problems.
        - IMPORTANT: NEVER suggest adding comments to the code
        
    Your code review should contain two priorites:
    Priority 1: Focus on bugs, security issues, integration problems
    Priority 2: Code quality improvements and performance improvements
    
    Prepend all <review comment> with the priority tag: <b> "PRIORTY 1" | "PRIORITY 2" <\b> \n <review comment>

    
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
    
    First take a look at the original code, step back and take a moment to understand the change contextually before reviewing. Leave nothing off the table.
    """

    def _get_openai_review(self, prompt: str) -> Dict[str, Any]:
        """
        Sends a code review prompt to Azure OpenAI and returns the parsed reviews.

        Args:
            prompt: The prompt containing the code diff and review instructions

        Returns:
            Dict with reviews field containing a list of review comments
        """
        messages = [
            {
                "role": "system",
                "content": "You are a Senior Software Engineer and have assigned reviewer for this PR. Provide specific, actionable feedback that helps improve code quality."
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
                response = self.client.beta.chat.completions.parse(
                    model=self.deployment,
                    response_format=FileReviews,
                    timeout=30,
                    messages=messages)

                # Get the parsed structured output directly
                return {"reviews": response.choices[0].message.parsed.reviews}

            except (AttributeError, ImportError):
                # Fall back to regular chat completions with JSON mode
                print("Falling back to regular JSON mode...")
                response = self.client.chat.completions.create(
                    model=self.deployment,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1000,
                    response_format={"type": "json_object"},
                    top_p=0.95
                )

                output = response.choices[0].message.content
                return json.loads(output)

        except Exception as e:
            print(f"Error during Azure OpenAI API call: {e}")
            return {"reviews": []}

    def _create_comment(self, file_path: str, hunk: Hunk, reviews: Dict[str, List]) -> List[Dict[str, Any]]:
        """
        Creates comment objects from AI responses.

        Args:
            file_path: Path to the file in the repository
            hunk: Hunk from the diff
            reviews: Reviews from OpenAI

        Returns:
            List of comments
        """
        print(f"Processing reviews for file: {file_path}")
        print(f"Hunk details - start: {hunk.source_start}, length: {hunk.source_length}")

        comments = []
        for review in reviews.get('reviews', []):
            try:
                # Handle both Pydantic model objects and dictionaries
                if hasattr(review, 'lineNumber') and hasattr(review, 'reviewComment'):
                    # It's a Pydantic model (from beta.chat.completions.parse)
                    line_number = int(review.lineNumber)
                    review_comment = review.reviewComment
                else:
                    # It's a dictionary (from regular chat.completions.create)
                    line_number = int(review.get('lineNumber', 0))
                    review_comment = review.get('reviewComment', '')

                if not line_number or not review_comment:
                    continue

                print(f"AI suggested line: {line_number}")

                # Ensure the line number is within the hunk's range
                if line_number < 1 or line_number > hunk.source_length:
                    print(f"Warning: Line number {line_number} is outside hunk range")
                    continue

                comment = {
                    "body": review_comment,
                    "path": file_path,
                    "position": line_number
                }
                print(f"Created comment for line {line_number}")
                comments.append(comment)

            except (KeyError, TypeError, ValueError) as e:
                print(f"Error creating comment from AI response: {e}, Response: {review}")

        return comments