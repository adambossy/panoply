"""CLI for code review agent."""

import asyncio
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from code_review_agent.agent import CodeReviewAgent

app = typer.Typer(
    name="code-review",
    help="AI-powered code review agent using Claude",
    no_args_is_help=True,
)
console = Console()


def get_agent(api_key: Optional[str] = None) -> CodeReviewAgent:
    """Create and return a CodeReviewAgent instance."""
    try:
        return CodeReviewAgent(api_key=api_key)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def review_file(
    file_path: Annotated[Path, typer.Argument(help="Path to file to review")],
    language: Annotated[str, typer.Option(help="Programming language")] = "python",
    focus: Annotated[
        Optional[str], typer.Option(help="Focus area (security, performance, style)")
    ] = None,
    api_key: Annotated[
        Optional[str], typer.Option(envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
    ] = None,
) -> None:
    """Review a code file for quality, bugs, and best practices."""
    if not file_path.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(1)

    console.print(f"[cyan]Reading file:[/cyan] {file_path}")
    try:
        code = file_path.read_text()
    except Exception as e:
        console.print(f"[red]Error reading file:[/red] {e}")
        raise typer.Exit(1)

    agent = get_agent(api_key)

    console.print("[cyan]Analyzing code...[/cyan]")

    async def run_review():
        return await agent.review_code(code, language=language, focus=focus)

    review = asyncio.run(run_review())

    console.print(Panel(Markdown(review), title="Code Review Results", border_style="green"))


@app.command()
def review_diff(
    diff_file: Annotated[
        Optional[Path], typer.Option(help="Path to diff file (default: read from git)")
    ] = None,
    staged: Annotated[bool, typer.Option(help="Review staged changes only")] = False,
    context: Annotated[Optional[str], typer.Option(help="Additional context")] = None,
    api_key: Annotated[
        Optional[str], typer.Option(envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
    ] = None,
) -> None:
    """Review code changes from a git diff."""
    import subprocess

    if diff_file:
        if not diff_file.exists():
            console.print(f"[red]Error:[/red] Diff file not found: {diff_file}")
            raise typer.Exit(1)
        diff = diff_file.read_text()
    else:
        # Get diff from git
        console.print("[cyan]Getting git diff...[/cyan]")
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, check=True
            )
            diff = result.stdout

            if not diff.strip():
                console.print("[yellow]No changes to review.[/yellow]")
                return
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error running git diff:[/red] {e.stderr}")
            raise typer.Exit(1)
        except subprocess.TimeoutExpired:
            console.print("[red]Error:[/red] Git diff timed out")
            raise typer.Exit(1)

    agent = get_agent(api_key)

    console.print("[cyan]Reviewing changes...[/cyan]")

    async def run_review():
        return await agent.review_diff(diff, context=context)

    review = asyncio.run(run_review())

    console.print(Panel(Markdown(review), title="Diff Review Results", border_style="green"))


@app.command()
def security_review(
    file_path: Annotated[Path, typer.Argument(help="Path to file to review")],
    language: Annotated[str, typer.Option(help="Programming language")] = "python",
    api_key: Annotated[
        Optional[str], typer.Option(envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
    ] = None,
) -> None:
    """Perform a security-focused code review."""
    if not file_path.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(1)

    console.print(f"[cyan]Reading file:[/cyan] {file_path}")
    try:
        code = file_path.read_text()
    except Exception as e:
        console.print(f"[red]Error reading file:[/red] {e}")
        raise typer.Exit(1)

    agent = get_agent(api_key)

    console.print("[cyan]Performing security analysis...[/cyan]")

    async def run_review():
        return await agent.security_review(code, language=language)

    review = asyncio.run(run_review())

    console.print(
        Panel(Markdown(review), title="Security Review Results", border_style="red")
    )


@app.command()
def suggest_improvements(
    file_path: Annotated[Path, typer.Argument(help="Path to file to improve")],
    language: Annotated[str, typer.Option(help="Programming language")] = "python",
    style_guide: Annotated[
        Optional[str], typer.Option(help="Style guide to follow (e.g., PEP 8)")
    ] = None,
    api_key: Annotated[
        Optional[str], typer.Option(envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
    ] = None,
) -> None:
    """Get suggestions for code improvements."""
    if not file_path.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(1)

    console.print(f"[cyan]Reading file:[/cyan] {file_path}")
    try:
        code = file_path.read_text()
    except Exception as e:
        console.print(f"[red]Error reading file:[/red] {e}")
        raise typer.Exit(1)

    agent = get_agent(api_key)

    console.print("[cyan]Analyzing and suggesting improvements...[/cyan]")

    async def run_review():
        return await agent.suggest_improvements(
            code, language=language, style_guide=style_guide
        )

    suggestions = asyncio.run(run_review())

    console.print(
        Panel(Markdown(suggestions), title="Improvement Suggestions", border_style="blue")
    )


@app.command()
def review_pr(
    files: Annotated[
        list[Path],
        typer.Argument(help="Paths to files in the pull request"),
    ],
    description: Annotated[
        Optional[str], typer.Option(help="Pull request description")
    ] = None,
    api_key: Annotated[
        Optional[str], typer.Option(envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
    ] = None,
) -> None:
    """Review multiple files as part of a pull request."""
    files_dict = {}

    for file_path in files:
        if not file_path.exists():
            console.print(f"[red]Error:[/red] File not found: {file_path}")
            raise typer.Exit(1)

        try:
            files_dict[str(file_path)] = file_path.read_text()
        except Exception as e:
            console.print(f"[red]Error reading {file_path}:[/red] {e}")
            raise typer.Exit(1)

    console.print(f"[cyan]Reviewing {len(files)} file(s)...[/cyan]")

    agent = get_agent(api_key)

    async def run_review():
        return await agent.review_pull_request(files_dict, pr_description=description)

    review = asyncio.run(run_review())

    console.print(Panel(Markdown(review), title="Pull Request Review", border_style="magenta"))


@app.command()
def stream_review(
    file_path: Annotated[Path, typer.Argument(help="Path to file to review")],
    review_type: Annotated[
        str, typer.Option(help="Review type: general, security, improvements")
    ] = "general",
    language: Annotated[str, typer.Option(help="Programming language")] = "python",
    api_key: Annotated[
        Optional[str], typer.Option(envvar="ANTHROPIC_API_KEY", help="Anthropic API key")
    ] = None,
) -> None:
    """Stream a code review for real-time feedback."""
    if not file_path.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(1)

    try:
        code = file_path.read_text()
    except Exception as e:
        console.print(f"[red]Error reading file:[/red] {e}")
        raise typer.Exit(1)

    agent = get_agent(api_key)

    console.print(f"[cyan]Streaming {review_type} review...[/cyan]\n")

    with agent.stream_review(code, review_type=review_type, language=language) as stream:
        for text in stream.text_stream:
            console.print(text, end="")

    console.print("\n")


if __name__ == "__main__":
    app()
