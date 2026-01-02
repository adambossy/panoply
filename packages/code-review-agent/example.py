#!/usr/bin/env python3
"""
Example usage of the CodeReviewAgent.

This demonstrates how to use the agent programmatically to review code.
To run this example, you need to set ANTHROPIC_API_KEY environment variable.
"""

import asyncio
import os
from pathlib import Path


async def main():
    # Import the agent (will work after uv sync completes)
    try:
        from code_review_agent import CodeReviewAgent
    except ImportError:
        print("Package not yet installed. Run: uv sync")
        print("Then run: uv run python packages/code-review-agent/example.py")
        return

    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("Set it with: export ANTHROPIC_API_KEY='sk-ant-...'")
        return

    # Initialize the agent
    print("Initializing CodeReviewAgent...\n")
    agent = CodeReviewAgent()

    # Read the agent's own code
    agent_file = Path(__file__).parent / "src/code_review_agent/agent.py"
    code = agent_file.read_text()

    # Example 1: General code review
    print("=" * 80)
    print("EXAMPLE 1: General Code Review")
    print("=" * 80)
    print(f"Reviewing: {agent_file}\n")

    review = await agent.review_code(code, language="python", focus="code quality")
    print(review)

    # Example 2: Security review
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Security Review")
    print("=" * 80)
    print(f"Security analysis of: {agent_file}\n")

    security_review = await agent.security_review(code, language="python")
    print(security_review)

    # Example 3: Improvement suggestions
    print("\n" + "=" * 80)
    print("EXAMPLE 3: Improvement Suggestions")
    print("=" * 80)

    suggestions = await agent.suggest_improvements(
        code, language="python", style_guide="PEP 8"
    )
    print(suggestions)

    # Example 4: Review a simple code snippet
    print("\n" + "=" * 80)
    print("EXAMPLE 4: Review Simple Code Snippet")
    print("=" * 80)

    sample_code = """
def calculate_total(items):
    total = 0
    for item in items:
        total += item['price']
    return total

def apply_discount(total, discount_percent):
    return total - (total * discount_percent / 100)
"""

    print("Reviewing sample code snippet:\n")
    snippet_review = await agent.review_code(sample_code, language="python")
    print(snippet_review)


if __name__ == "__main__":
    asyncio.run(main())
