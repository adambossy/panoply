"""Core code review agent implementation using Claude Agent SDK."""

import os
from typing import AsyncIterator

from anthropic import Anthropic
from anthropic.types import Message, MessageStreamEvent


class CodeReviewAgent:
    """
    AI-powered code review agent using Claude's API.

    This agent can review code changes, analyze files for security issues,
    suggest improvements, and provide detailed feedback on code quality.
    """

    def __init__(self, api_key: str | None = None, model: str = "claude-opus-4-5-20251101"):
        """
        Initialize the code review agent.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Claude model to use for reviews
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.client = Anthropic(api_key=self.api_key)
        self.model = model
        self.max_tokens = 8192

    async def review_code(
        self, code: str, language: str = "python", focus: str | None = None
    ) -> str:
        """
        Review a code snippet for quality, bugs, and best practices.

        Args:
            code: The code to review
            language: Programming language of the code
            focus: Optional focus area (e.g., 'security', 'performance', 'style')

        Returns:
            Detailed code review feedback
        """
        focus_prompt = f"\nFocus especially on: {focus}" if focus else ""

        prompt = f"""
Please review the following {language} code for:
1. Potential bugs or errors
2. Security vulnerabilities
3. Code quality and best practices
4. Performance issues
5. Readability and maintainability{focus_prompt}

Provide specific, actionable feedback with examples where appropriate.

Code to review:
```{language}
{code}
```
"""

        message = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, messages=[{"role": "user", "content": prompt}]
        )

        return message.content[0].text

    async def review_diff(self, diff: str, context: str | None = None) -> str:
        """
        Review a git diff for code quality and potential issues.

        Args:
            diff: Git diff output
            context: Optional additional context about the changes

        Returns:
            Code review feedback focusing on the changes
        """
        context_prompt = f"\nContext: {context}" if context else ""

        prompt = f"""
Review the following code changes (git diff). Focus on:
1. Changes that introduce bugs
2. Security implications of the changes
3. Code quality improvements
4. Potential breaking changes
5. Suggestions for better implementation{context_prompt}

Git Diff:
```diff
{diff}
```

Provide a structured review with:
- Summary of changes
- Issues found (if any)
- Recommendations
- Overall assessment
"""

        message = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, messages=[{"role": "user", "content": prompt}]
        )

        return message.content[0].text

    async def security_review(self, code: str, language: str = "python") -> str:
        """
        Perform a security-focused code review.

        Args:
            code: Code to review for security issues
            language: Programming language

        Returns:
            Security-focused review findings
        """
        prompt = f"""
Perform a comprehensive security review of this {language} code.

Look for:
- SQL injection vulnerabilities
- Authentication/authorization issues
- Credential leaks or hardcoded secrets
- Insecure cryptography
- Input validation problems
- OWASP Top 10 vulnerabilities
- Command injection risks
- XSS vulnerabilities
- Path traversal issues
- Insecure deserialization

Provide:
1. List of security findings with severity (Critical/High/Medium/Low)
2. Detailed explanation of each issue
3. Remediation steps with code examples
4. Overall security assessment

Code:
```{language}
{code}
```
"""

        message = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, messages=[{"role": "user", "content": prompt}]
        )

        return message.content[0].text

    async def suggest_improvements(
        self, code: str, language: str = "python", style_guide: str | None = None
    ) -> str:
        """
        Suggest code improvements for better quality and maintainability.

        Args:
            code: Code to improve
            language: Programming language
            style_guide: Optional style guide to follow (e.g., 'PEP 8', 'Google')

        Returns:
            Improvement suggestions with examples
        """
        style_prompt = f"\nFollow {style_guide} style guide." if style_guide else ""

        prompt = f"""
Analyze this {language} code and suggest improvements for:
1. Code organization and structure
2. Naming conventions
3. Design patterns
4. Error handling
5. Documentation
6. Type hints (if applicable)
7. Performance optimizations{style_prompt}

For each suggestion:
- Explain what to improve
- Show the improved code
- Explain why it's better

Current code:
```{language}
{code}
```
"""

        message = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, messages=[{"role": "user", "content": prompt}]
        )

        return message.content[0].text

    async def review_pull_request(
        self, files: dict[str, str], pr_description: str | None = None
    ) -> str:
        """
        Review multiple files as part of a pull request.

        Args:
            files: Dictionary mapping file paths to their content
            pr_description: Optional PR description for context

        Returns:
            Comprehensive PR review
        """
        files_content = "\n\n".join(
            [f"File: {path}\n```\n{content}\n```" for path, content in files.items()]
        )

        pr_context = (
            f"\nPR Description: {pr_description}\n" if pr_description else ""
        )

        prompt = f"""
Review this pull request with {len(files)} file(s).{pr_context}

Provide:
1. Summary of the changes
2. File-by-file review with specific feedback
3. Overall code quality assessment
4. Security considerations
5. Testing recommendations
6. Approval recommendation (Approve/Request Changes/Comment)

Files:
{files_content}
"""

        message = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, messages=[{"role": "user", "content": prompt}]
        )

        return message.content[0].text

    def stream_review(
        self, code: str, review_type: str = "general", **kwargs
    ) -> AsyncIterator[MessageStreamEvent]:
        """
        Stream a code review response for real-time feedback.

        Args:
            code: Code to review
            review_type: Type of review ('general', 'security', 'improvements')
            **kwargs: Additional arguments for specific review types

        Returns:
            Async iterator of message stream events
        """
        if review_type == "security":
            language = kwargs.get("language", "python")
            prompt = f"Perform a security review of this {language} code:\n\n```{language}\n{code}\n```"
        elif review_type == "improvements":
            language = kwargs.get("language", "python")
            prompt = f"Suggest improvements for this {language} code:\n\n```{language}\n{code}\n```"
        else:
            language = kwargs.get("language", "python")
            prompt = f"Review this {language} code:\n\n```{language}\n{code}\n```"

        return self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
