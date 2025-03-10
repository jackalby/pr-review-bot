#!/usr/bin/env python3

from typing import List, Dict, Any
from core.models import FileChange


class DiffParser:
    """Parser for Git diff output."""

    @staticmethod
    def parse_diff(diff_str: str) -> List[FileChange]:
        """
        Parses the diff string and returns a structured format.

        Args:
            diff_str: Git diff string

        Returns:
            List of FileChange objects
        """
        files = []
        current_file = None
        current_hunk = None

        for line in diff_str.splitlines():
            if line.startswith('diff --git'):
                if current_file:
                    files.append(FileChange(current_file['path'], current_file['hunks']))
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
            files.append(FileChange(current_file['path'], current_file['hunks']))

        return files