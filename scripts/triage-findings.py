"""Triage SAST findings using LLM analysis.

Reads a Semgrep JSON report, sends each finding to an LLM for triage,
and optionally posts results to a merge/pull request.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests


def load_prompt(prompt_file: str) -> str:
    with open(prompt_file) as f:
        return f.read()


def extract_code_context(finding: dict) -> str:
    """Extract relevant code context from a Semgrep finding."""
    path = finding.get("path", "unknown")
    start_line = finding.get("start", {}).get("line", 0)
    end_line = finding.get("end", {}).get("line", 0)
    lines = finding.get("extra", {}).get("lines", "")
    message = finding.get("extra", {}).get("message", "")
    check_id = finding.get("check_id", "unknown")
    severity = finding.get("extra", {}).get("severity", "unknown")

    return (
        f"**Finding:** `{check_id}` (severity: {severity})\n"
        f"**File:** `{path}:{start_line}-{end_line}`\n"
        f"**Message:** {message}\n"
        f"**Code:**\n```\n{lines}\n```"
    )


def fetch_tabby_context(tabby_url: str, filepath: str, line_start: int, line_end: int) -> str:
    """Fetch cross-file context from TabbyML."""
    try:
        resp = requests.post(
            f"{tabby_url}/v1beta/chat/completions",
            json={
                "messages": [{"role": "user", "content": f"Find callers and definitions related to {filepath}:{line_start}-{line_end}"}],
            },
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                return f"\n## Related Code Context\n{content}"
    except Exception as e:
        print(f"Warning: TabbyML context fetch failed: {e}", file=sys.stderr)
    return ""


def chat_completion(llm_url: str, model: str, engine: str, messages: list[dict]) -> dict:
    """Send chat completion request to LLM."""
    if engine == "vllm":
        url = f"{llm_url}/v1/chat/completions"
        payload = {"model": model, "messages": messages, "temperature": 0.1}
    else:
        url = f"{llm_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1},
        }

    last_exc = None
    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            if engine == "vllm":
                return data["choices"][0]["message"]["content"]
            else:
                return data.get("message", {}).get("content", "")
        except requests.exceptions.Timeout as e:
            print(f"    LLM timeout on attempt {attempt}/3: {e}", file=sys.stderr)
            last_exc = e
        except Exception as e:
            print(f"    LLM error on attempt {attempt}/3: {e}", file=sys.stderr)
            last_exc = e
        if attempt < 3:
            time.sleep(2 ** attempt)
    raise last_exc


def parse_verdict(response_text: str) -> dict:
    """Parse JSON verdict from LLM response."""
    # Try to extract JSON from the response
    text = response_text.strip()
    # Handle markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        result = json.loads(text)
        return {
            "verdict": result.get("verdict", "needs_review"),
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", ""),
        }
    except (json.JSONDecodeError, ValueError):
        return {
            "verdict": "needs_review",
            "confidence": 0.0,
            "reasoning": f"Failed to parse LLM response: {response_text[:200]}",
        }


def post_to_gitlab(git_url: str, git_token: str, project_path: str, mr_id: str, body: str) -> None:
    """Post comment to GitLab MR."""
    # URL-encode the project path
    encoded_path = project_path.replace("/", "%2F")
    url = f"{git_url}/api/v4/projects/{encoded_path}/merge_requests/{mr_id}/notes"
    resp = requests.post(
        url,
        headers={"PRIVATE-TOKEN": git_token},
        json={"body": body},
        timeout=30,
    )
    if resp.status_code in (200, 201):
        print(f"Posted triage summary to MR #{mr_id}")
    else:
        print(f"Failed to post to MR: HTTP {resp.status_code} - {resp.text}", file=sys.stderr)


def post_to_gitea(git_url: str, git_token: str, repo: str, pr_id: str, body: str) -> None:
    """Post comment to Gitea PR."""
    url = f"{git_url}/api/v1/repos/{repo}/issues/{pr_id}/comments"
    resp = requests.post(
        url,
        headers={"Authorization": f"token {git_token}"},
        json={"body": body},
        timeout=30,
    )
    if resp.status_code in (200, 201):
        print(f"Posted triage summary to PR #{pr_id}")
    else:
        print(f"Failed to post to PR: HTTP {resp.status_code} - {resp.text}", file=sys.stderr)


def format_markdown_table(results: list[dict]) -> str:
    """Format triage results as a markdown table."""
    lines = [
        "## SAST Triage Results",
        "",
        "| Finding | File | Verdict | Confidence | Reasoning |",
        "|---------|------|---------|------------|-----------|",
    ]
    for r in results:
        verdict_emoji = {"true_positive": "🔴", "false_positive": "🟢", "needs_review": "🟡"}.get(
            r["verdict"], "⚪"
        )
        lines.append(
            f"| `{r['check_id']}` | `{r['file']}:{r['line']}` | {verdict_emoji} {r['verdict']} | {r['confidence']:.0%} | {r['reasoning'][:80]} |"
        )

    tp = sum(1 for r in results if r["verdict"] == "true_positive")
    fp = sum(1 for r in results if r["verdict"] == "false_positive")
    nr = sum(1 for r in results if r["verdict"] == "needs_review")
    lines.append("")
    lines.append(f"**Summary:** {tp} true positives, {fp} false positives, {nr} needs review")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage SAST findings with LLM")
    parser.add_argument("--report", required=True, help="Path to semgrep_report.json")
    parser.add_argument("--prompt-file", required=True, help="Path to triage prompt template")
    parser.add_argument("--llm-url", required=True, help="LLM API base URL")
    parser.add_argument("--model", required=True, help="Model name")
    parser.add_argument("--engine", default="ollama", choices=["ollama", "vllm"], help="Inference engine")
    parser.add_argument("--tabby-url", default=None, help="TabbyML URL for cross-file context")
    parser.add_argument("--git-platform", choices=["gitlab", "gitea"], help="Git platform for posting")
    parser.add_argument("--git-url", help="Git platform base URL")
    parser.add_argument("--git-token", help="Git platform access token")
    parser.add_argument("--project", help="Project path (GitLab) or owner/repo (Gitea)")
    parser.add_argument("--mr-id", help="MR/PR number to post comment to")
    parser.add_argument("--output", default="triage_results.json", help="Output JSON file")
    args = parser.parse_args()

    # Validate output path stays within current directory tree
    output_path = Path(args.output).resolve()
    cwd = Path.cwd().resolve()
    try:
        output_path.relative_to(cwd)
    except ValueError:
        print(f"Error: Output path {args.output!r} escapes the working directory", file=sys.stderr)
        sys.exit(1)

    # Load report
    if not os.path.exists(args.report):
        print(f"Error: Report not found: {args.report}", file=sys.stderr)
        sys.exit(1)

    with open(args.report) as f:
        report = json.load(f)

    findings = report.get("results", [])
    if not findings:
        print("No findings to triage.")
        with open(output_path, "w") as f:
            json.dump([], f)
        sys.exit(0)

    # Load prompt template
    prompt_template = load_prompt(args.prompt_file)

    print(f"Triaging {len(findings)} findings...")
    results = []

    for i, finding in enumerate(findings):
        check_id = finding.get("check_id", "unknown")
        path = finding.get("path", "unknown")
        line = finding.get("start", {}).get("line", 0)

        print(f"  [{i+1}/{len(findings)}] {check_id} at {path}:{line}")

        code_context = extract_code_context(finding)

        # Optional: fetch cross-file context from TabbyML
        tabby_context = ""
        if args.tabby_url:
            end_line = finding.get("end", {}).get("line", line)
            tabby_context = fetch_tabby_context(args.tabby_url, path, line, end_line)

        messages = [
            {"role": "system", "content": prompt_template},
            {"role": "user", "content": f"{code_context}{tabby_context}"},
        ]

        try:
            response = chat_completion(args.llm_url, args.model, args.engine, messages)
            verdict = parse_verdict(response)
        except Exception as e:
            print(f"    Error: {e}", file=sys.stderr)
            verdict = {"verdict": "needs_review", "confidence": 0.0, "reasoning": str(e)}

        results.append({
            "check_id": check_id,
            "file": path,
            "line": line,
            **verdict,
        })

    # Write results
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {args.output}")

    # Post to MR/PR if configured
    if args.git_platform and args.git_url and args.git_token and args.mr_id and args.project:
        body = format_markdown_table(results)
        if args.git_platform == "gitlab":
            post_to_gitlab(args.git_url, args.git_token, args.project, args.mr_id, body)
        elif args.git_platform == "gitea":
            post_to_gitea(args.git_url, args.git_token, args.project, args.mr_id, body)


if __name__ == "__main__":
    main()
