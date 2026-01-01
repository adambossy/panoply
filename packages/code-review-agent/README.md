# Code Review Agent

An AI-powered code review agent using Claude's Anthropic API. This tool provides automated code reviews, security analysis, and improvement suggestions for your codebase.

## Features

- **Code Review**: Comprehensive analysis of code quality, bugs, and best practices
- **Security Review**: Security-focused analysis checking for common vulnerabilities
- **Diff Review**: Review git changes and pull requests
- **Improvement Suggestions**: Get actionable suggestions for code improvements
- **Streaming Support**: Real-time feedback as the analysis progresses

## Installation

This package is part of the Panoply monorepo workspace. Install dependencies:

```bash
# From the repository root
uv sync
```

## Setup

Set your Anthropic API key as an environment variable:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or add it to your `.env` file in the repository root:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
```

## Usage

The package provides a `code-review` CLI command with several subcommands.

### Review a File

Review a single file for code quality, bugs, and best practices:

```bash
uv run --package code-review-agent code-review review-file path/to/file.py
```

With optional focus area:

```bash
uv run --package code-review-agent code-review review-file path/to/file.py --focus security
```

### Review Git Changes

Review uncommitted changes:

```bash
uv run --package code-review-agent code-review review-diff
```

Review staged changes:

```bash
uv run --package code-review-agent code-review review-diff --staged
```

Review from a diff file:

```bash
uv run --package code-review-agent code-review review-diff --diff-file changes.diff
```

### Security Review

Perform a security-focused review:

```bash
uv run --package code-review-agent code-review security-review path/to/file.py
```

### Get Improvement Suggestions

Get actionable suggestions for code improvements:

```bash
uv run --package code-review-agent code-review suggest-improvements path/to/file.py
```

With style guide:

```bash
uv run --package code-review-agent code-review suggest-improvements path/to/file.py --style-guide "PEP 8"
```

### Review Pull Request

Review multiple files together:

```bash
uv run --package code-review-agent code-review review-pr file1.py file2.py file3.py
```

With PR description for context:

```bash
uv run --package code-review-agent code-review review-pr file1.py file2.py --description "Add user authentication"
```

### Stream Review

Get real-time streaming feedback:

```bash
uv run --package code-review-agent code-review stream-review path/to/file.py
```

With specific review type:

```bash
uv run --package code-review-agent code-review stream-review path/to/file.py --review-type security
```

## Programmatic Usage

You can also use the agent programmatically in Python:

```python
import asyncio
from code_review_agent import CodeReviewAgent

async def main():
    # Initialize the agent
    agent = CodeReviewAgent()

    # Review code
    code = """
    def calculate_total(items):
        total = 0
        for item in items:
            total += item.price
        return total
    """

    review = await agent.review_code(code, language="python")
    print(review)

    # Security review
    security_report = await agent.security_review(code, language="python")
    print(security_report)

    # Get improvements
    suggestions = await agent.suggest_improvements(code, language="python")
    print(suggestions)

if __name__ == "__main__":
    asyncio.run(main())
```

## API Reference

### CodeReviewAgent

The main agent class for performing code reviews.

#### Methods

- `review_code(code: str, language: str, focus: str | None) -> str`
  - Review code for quality, bugs, and best practices

- `review_diff(diff: str, context: str | None) -> str`
  - Review git diff changes

- `security_review(code: str, language: str) -> str`
  - Perform security-focused review

- `suggest_improvements(code: str, language: str, style_guide: str | None) -> str`
  - Get improvement suggestions

- `review_pull_request(files: dict[str, str], pr_description: str | None) -> str`
  - Review multiple files as a pull request

- `stream_review(code: str, review_type: str, **kwargs) -> AsyncIterator`
  - Stream review for real-time feedback

## Configuration

The agent uses Claude Opus 4.5 by default. You can customize the model when initializing:

```python
agent = CodeReviewAgent(model="claude-sonnet-4-5-20251101")
```

## Development

### Running Tests

```bash
# Run tests for this package
uv run --package code-review-agent pytest
```

### Type Checking

```bash
# Type check this package
uv run mypy packages/code-review-agent
```

### Linting

```bash
# Lint this package
uv run ruff check packages/code-review-agent
```

## Examples

### Example: Review Current Branch Changes

```bash
# Review all uncommitted changes
uv run --package code-review-agent code-review review-diff

# Review only staged changes
uv run --package code-review-agent code-review review-diff --staged
```

### Example: Security Audit

```bash
# Review authentication module for security issues
uv run --package code-review-agent code-review security-review src/auth.py
```

### Example: Pre-commit Hook

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
uv run --package code-review-agent code-review review-diff --staged
```

## Requirements

- Python 3.12+
- Anthropic API key
- Dependencies: `anthropic`, `typer`, `rich`

## License

Part of the Panoply monorepo.
