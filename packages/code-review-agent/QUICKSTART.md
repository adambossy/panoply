# Quick Start Guide

## Setup

1. **Install dependencies** (once network connectivity is restored):
   ```bash
   cd /home/user/panoply
   uv sync
   ```

2. **Set your API key**:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-your-key-here"
   ```

   Or add to `.env`:
   ```bash
   echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" >> .env
   ```

## Test the Agent

### Option 1: Review the Agent's Own Code

The best way to test the agent is to have it review itself!

```bash
# Review the core agent implementation
uv run --package code-review-agent code-review review-file \
  packages/code-review-agent/src/code_review_agent/agent.py

# Security review of the CLI
uv run --package code-review-agent code-review security-review \
  packages/code-review-agent/src/code_review_agent/cli.py

# Get improvement suggestions for the tools module
uv run --package code-review-agent code-review suggest-improvements \
  packages/code-review-agent/src/code_review_agent/tools.py
```

### Option 2: Run the Example Script

```bash
uv run python packages/code-review-agent/example.py
```

This will demonstrate:
1. General code review
2. Security analysis
3. Improvement suggestions
4. Simple code snippet review

### Option 3: Review Your Own Code

```bash
# Review a Python file
uv run --package code-review-agent code-review review-file \
  packages/financial_analysis/src/financial_analysis/cli.py

# Review current git changes
uv run --package code-review-agent code-review review-diff

# Review staged changes only
uv run --package code-review-agent code-review review-diff --staged
```

## What to Expect

The agent will analyze the code and provide:

### For General Review:
- Potential bugs or errors
- Code quality issues
- Best practice violations
- Performance concerns
- Readability improvements

### For Security Review:
- Security vulnerabilities (SQL injection, XSS, etc.)
- Hardcoded credentials or secrets
- Insecure cryptography
- Input validation issues
- OWASP Top 10 vulnerabilities

### For Improvement Suggestions:
- Code organization improvements
- Better naming conventions
- Design pattern recommendations
- Error handling enhancements
- Documentation suggestions
- Type hint additions

## Example Output

When you run a review, you'll see rich formatted output like:

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Code Review Results                                ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

# Code Review

## Overview
This Python code implements a code review agent...

## Issues Found

### 1. Missing Type Hints
**Severity:** Low
**Location:** Multiple methods
...

## Recommendations
1. Add comprehensive docstrings
2. Implement error handling for API failures
...
```

## Programmatic Usage

You can also use the agent in your own Python scripts:

```python
import asyncio
from code_review_agent import CodeReviewAgent

async def review_my_code():
    agent = CodeReviewAgent()

    with open("my_file.py") as f:
        code = f.read()

    review = await agent.review_code(code, language="python")
    print(review)

asyncio.run(review_my_code())
```

## Troubleshooting

### "ANTHROPIC_API_KEY not set"
Make sure you've exported the environment variable or added it to `.env`

### "Package not yet installed"
Run `uv sync` from the repository root to install all workspace packages

### Network issues with uv sync
The installer needs to download Python and dependencies. Ensure you have internet connectivity.

### "Request failed"
Check your API key is valid and you have credits in your Anthropic account
