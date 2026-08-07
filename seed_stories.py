#!/usr/bin/env python3
"""
Seed GitHub issues + sub-issues from stories.yml and load them onto a Project board.

Prereqs:
    gh auth login
    gh auth refresh -s project,read:project    # project scopes are NOT granted by default
    pip install pyyaml

Usage:
    python seed_stories.py --repo kim-cates/mirra --owner kim-cates --project 1 --dry-run
    python seed_stories.py --repo kim-cates/mirra --owner kim-cates --project 1
"""

import argparse
import json
import os
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

import yaml

DRY = False

# Standard install locations, checked when 'gh' isn't on PATH. The winget/MSI
# installer writes its directory to the *machine* PATH, so terminals opened
# before the install (VS Code included) never see it until they're restarted.
GH_FALLBACK_DIRS = [
    r"C:\Program Files\GitHub CLI",
    r"C:\Program Files (x86)\GitHub CLI",
    os.path.expandvars(r"%LOCALAPPDATA%\GitHubCLI"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\GitHub CLI"),
    os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
    r"C:\ProgramData\chocolatey\bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
]


def find_gh():
    """Resolve the gh executable, falling back to known install dirs."""
    found = shutil.which("gh")
    if found:
        return found
    for directory in GH_FALLBACK_DIRS:
        for name in ("gh.exe", "gh"):
            candidate = Path(directory) / name
            if candidate.is_file():
                return str(candidate)
    sys.exit(
        "GitHub CLI ('gh') not found on PATH or in any standard install location.\n"
        "Install it from https://cli.github.com/ , or if it is already installed,\n"
        "open a new terminal so the updated PATH is picked up."
    )


GH = None  # resolved once in main()


def run(args, check=True):
    """Run a command, return stdout. Exit loudly on failure."""
    # Substitute the resolved absolute path so we never depend on PATH lookup.
    if args and args[0] == "gh" and GH:
        args = [GH] + list(args[1:])

    if DRY:
        print(f"  [dry-run] {' '.join(args)}")
        return ""

    try:
        # Force UTF-8: gh emits UTF-8, but text=True decodes with the locale
        # codec (cp1252 on Windows), which dies on smart quotes/em dashes and
        # leaves proc.stdout as None.
        proc = subprocess.run(args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        sys.exit(
            f"Command not found: {args[0]}.\nPlease install the required CLI and ensure it's on PATH.\nSee https://cli.github.com/ for the GitHub CLI ('gh')."
        )

    if check and proc.returncode != 0:
        sys.exit(f"\nFAILED: {' '.join(args)}\n{proc.stderr}")
    return proc.stdout.strip()


def preflight():
    """Fail early with an actionable message if gh isn't authed with project scopes."""
    proc = subprocess.run([GH, "auth", "status"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.exit(f"gh is installed but not authenticated. Run:\n    gh auth login\n\n{proc.stderr}")

    scopes_line = next(
        (ln for ln in (proc.stdout + proc.stderr).splitlines() if "Token scopes:" in ln), ""
    )
    # Seeding writes to the board (field-create, item-add, item-edit), so the
    # full 'project' scope is required. 'read:project' is read-only and is NOT
    # sufficient — it lets `gh project list` succeed while every write fails.
    if "'project'" not in scopes_line:
        sys.exit(
            "Your gh token lacks the 'project' scope, so the board can't be written to.\n"
            f"Current scopes: {scopes_line.strip() or 'unknown'}\n\n"
            "Note: 'read:project' is read-only and is not enough.\n"
            "Run this once, in your own terminal (it opens a browser):\n"
            "    gh auth refresh -s project\n"
        )


def run_json(args):
    out = run(args)
    return json.loads(out) if out else {}


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------

def ensure_labels(repo, labels):
    print("Ensuring labels...")
    for name, meta in labels.items():
        run([
            "gh", "label", "create", name,
            "--repo", repo,
            "--color", meta["color"],
            "--description", meta.get("description", ""),
            "--force",  # idempotent: updates if it already exists
        ])
        print(f"  {name}")


# --------------------------------------------------------------------------
# Issues
# --------------------------------------------------------------------------

def create_issue(repo, title, body, labels):
    """Create an issue and return (url, node_id)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(body)
        body_path = fh.name

    args = ["gh", "issue", "create", "--repo", repo,
            "--title", title, "--body-file", body_path]
    for label in labels:
        args += ["--label", label]

    url = run(args)
    Path(body_path).unlink(missing_ok=True)

    if DRY:
        return f"https://github.com/{repo}/issues/DRY", "DRY_NODE_ID"

    number = url.rstrip("/").split("/")[-1]
    node_id = run(["gh", "issue", "view", number, "--repo", repo,
                   "--json", "id", "-q", ".id"])
    return url, node_id


def link_sub_issue(parent_node_id, child_node_id):
    """Attach child as a native GitHub sub-issue of parent."""
    mutation = """
    mutation($parent: ID!, $child: ID!) {
      addSubIssue(input: {issueId: $parent, subIssueId: $child}) {
        issue { number }
      }
    }
    """
    run([
        "gh", "api", "graphql",
        "-H", "GraphQL-Features: sub_issues",
        "-f", f"query={mutation}",
        "-F", f"parent={parent_node_id}",
        "-F", f"child={child_node_id}",
    ])


# --------------------------------------------------------------------------
# Project board
# --------------------------------------------------------------------------

def project_meta(owner, number):
    """Return (project_node_id, {field_name: field_dict})."""
    if DRY:
        return "DRY_PROJECT_ID", {}
    pid = run(["gh", "project", "view", str(number), "--owner", owner,
               "--format", "json", "-q", ".id"])
    fields = run_json(["gh", "project", "field-list", str(number),
                       "--owner", owner, "--format", "json"])
    return pid, {f["name"]: f for f in fields.get("fields", [])}


def ensure_number_field(owner, number, fields, name):
    """Create a NUMBER field if it doesn't exist. Returns field id or None."""
    if name in fields:
        return fields[name]["id"]
    print(f"  creating project field '{name}'")
    run(["gh", "project", "field-create", str(number), "--owner", owner,
         "--name", name, "--data-type", "NUMBER"])
    _, refreshed = project_meta(owner, number)
    return refreshed.get(name, {}).get("id")


def add_to_project(owner, number, url):
    """Add an issue to the project, return the project item id."""
    if DRY:
        run(["gh", "project", "item-add", str(number), "--owner", owner, "--url", url])
        return "DRY_ITEM_ID"
    res = run_json(["gh", "project", "item-add", str(number), "--owner", owner,
                    "--url", url, "--format", "json"])
    return res.get("id")


def set_number(project_id, item_id, field_id, value):
    if not field_id:
        return
    run(["gh", "project", "item-edit", "--id", item_id,
         "--project-id", project_id, "--field-id", field_id,
         "--number", str(value)])


def set_single_select(project_id, item_id, field, option_name):
    if not field:
        return
    option = next((o for o in field.get("options", [])
                   if o["name"].lower() == option_name.lower()), None)
    if not option:
        print(f"  ! no '{option_name}' option on {field['name']}, skipping")
        return
    run(["gh", "project", "item-edit", "--id", item_id,
         "--project-id", project_id, "--field-id", field["id"],
         "--single-select-option-id", option["id"]])


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    global DRY, GH
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--owner", required=True, help="project owner (user or org)")
    ap.add_argument("--project", required=True, type=int, help="project number")
    ap.add_argument("--file", default="stories.yml")
    ap.add_argument("--status", default="Todo", help="initial Status column")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    DRY = args.dry_run
    if DRY:
        print("=== DRY RUN — no writes ===\n")

    GH = find_gh()
    print(f"Using gh: {GH}")
    if not DRY:
        preflight()

    # stories.yml is UTF-8; without this it decodes as cp1252 on Windows and
    # every em dash / smart quote reaches GitHub as mojibake.
    data = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))

    ensure_labels(args.repo, data.get("labels", {}))

    project_id, fields = project_meta(args.owner, args.project)
    points_field_id = ensure_number_field(args.owner, args.project, fields, "Story Points")
    _, fields = project_meta(args.owner, args.project)
    status_field = fields.get("Status")

    created = {}

    for story in data["stories"]:
        print(f"\n{story['key']}")

        body = story["body"]
        if story.get("blocked_by"):
            blocker = created.get(story["blocked_by"])
            if blocker:
                body += f"\n\n**Blocked by:** {blocker['url']}\n"

        url, node_id = create_issue(args.repo, story["title"], body, story["labels"])
        created[story["key"]] = {"url": url, "node_id": node_id}
        print(f"  parent -> {url}")

        item_id = add_to_project(args.owner, args.project, url)
        set_number(project_id, item_id, points_field_id, story.get("points", 0))
        set_single_select(project_id, item_id, status_field, args.status)

        for sub in story.get("sub_issues", []):
            sub_body = f"Sub-issue of {url}\n\n{sub.get('body', '')}".strip()
            sub_url, sub_node = create_issue(
                args.repo, sub["title"], sub_body, sub.get("labels", ["task"])
            )
            link_sub_issue(node_id, sub_node)
            add_to_project(args.owner, args.project, sub_url)
            print(f"    sub -> {sub['title']}")

    print(f"\nDone. {len(created)} stories seeded.")
    print(f"Board: https://github.com/users/{args.owner}/projects/{args.project}")


if __name__ == "__main__":
    main()
