import subprocess
from pathlib import Path


def recent_branches(cwd: Path, n: int = 10) -> list[str]:
    """Last N local branches sorted by most recently committed."""
    r = subprocess.run(
        ["git", "branch", "--sort=-committerdate", "--format=%(refname:short)"],
        capture_output=True, text=True, cwd=cwd,
    )
    if r.returncode != 0:
        return []
    return [b.strip() for b in r.stdout.splitlines() if b.strip()][:n]


def branches_matching(ticket_id: str, cwd: Path) -> list[str]:
    """Local branches whose name contains ticket_id (case-insensitive glob)."""
    r = subprocess.run(
        ["git", "branch", "--list", f"*{ticket_id}*", "--format=%(refname:short)"],
        capture_output=True, text=True, cwd=cwd,
    )
    if r.returncode != 0:
        return []
    return [b.strip() for b in r.stdout.splitlines() if b.strip()]


def checkout(branch: str, cwd: Path) -> tuple[bool, str]:
    """Returns (success, stderr)."""
    r = subprocess.run(
        ["git", "checkout", branch],
        capture_output=True, text=True, cwd=cwd,
    )
    return r.returncode == 0, r.stderr.strip()
