"""Custom tools for code review agent."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GetGitDiffInput:
    """Input schema for git diff tool."""

    file_path: str | None = None
    context_lines: int = 3
    staged: bool = False


async def get_git_diff(input: GetGitDiffInput) -> dict[str, Any]:
    """
    Retrieve git diff to understand recent changes.

    Args:
        file_path: Optional specific file to get diff for (None = all files)
        context_lines: Number of context lines to show
        staged: If True, show staged changes only
    """
    try:
        cmd = ["git", "diff", "--unified", str(input.context_lines)]

        if input.staged:
            cmd.append("--staged")

        if input.file_path:
            cmd.append(input.file_path)

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, check=False
        )

        if result.returncode != 0 and result.stderr:
            return {"diff": "", "error": result.stderr}

        return {"diff": result.stdout, "error": None}
    except subprocess.TimeoutExpired:
        return {"diff": "", "error": "Git diff command timed out"}
    except Exception as e:
        return {"diff": "", "error": str(e)}


@dataclass
class GetGitStatusInput:
    """Input schema for git status tool."""

    short_format: bool = True


async def get_git_status(input: GetGitStatusInput) -> dict[str, Any]:
    """
    Get git repository status to see changed files.

    Args:
        short_format: Use short format output
    """
    try:
        cmd = ["git", "status"]
        if input.short_format:
            cmd.append("--short")

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, check=False
        )

        if result.returncode != 0:
            return {"status": "", "error": result.stderr}

        return {"status": result.stdout, "error": None}
    except subprocess.TimeoutExpired:
        return {"status": "", "error": "Git status command timed out"}
    except Exception as e:
        return {"status": "", "error": str(e)}


@dataclass
class AnalyzeFileInput:
    """Input schema for file analysis tool."""

    file_path: str
    check_types: list[str] | None = None


async def analyze_file(input: AnalyzeFileInput) -> dict[str, Any]:
    """
    Analyze a file for common issues.

    Args:
        file_path: Path to the file to analyze
        check_types: Types of checks to perform (e.g., ['security', 'style', 'bugs'])
    """
    file_path = Path(input.file_path)

    if not file_path.exists():
        return {"issues": [], "error": f"File not found: {input.file_path}"}

    try:
        content = file_path.read_text()
    except Exception as e:
        return {"issues": [], "error": f"Error reading file: {e}"}

    issues = []
    check_types = input.check_types or ["all"]

    # Basic pattern matching for common issues
    if "security" in check_types or "all" in check_types:
        # Check for potential security issues
        if "eval(" in content or "exec(" in content:
            issues.append(
                {
                    "type": "security",
                    "severity": "high",
                    "message": "Dangerous use of eval() or exec() detected",
                }
            )

        if "password" in content.lower() and ("=" in content or ":" in content):
            issues.append(
                {
                    "type": "security",
                    "severity": "medium",
                    "message": "Possible hardcoded password or credential",
                }
            )

    if "style" in check_types or "all" in check_types:
        # Check for style issues
        if "TODO" in content or "FIXME" in content:
            issues.append(
                {
                    "type": "style",
                    "severity": "low",
                    "message": "Unresolved TODO/FIXME comments found",
                }
            )

    if "bugs" in check_types or "all" in check_types:
        # Check for potential bugs
        if "except:" in content or "except :" in content:
            issues.append(
                {
                    "type": "bugs",
                    "severity": "medium",
                    "message": "Bare except clause found - may hide errors",
                }
            )

    return {"issues": issues, "summary": f"Found {len(issues)} potential issues"}
