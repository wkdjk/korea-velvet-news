"""
deploy.py — Push generated HTML + CSS to the gh-pages branch.

Copies output/index.html and templates/static/ to a temporary gh-pages checkout,
then force-pushes to the gh-pages branch. Runs inside GitHub Actions where
GITHUB_TOKEN is available automatically.
"""

import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_OUTPUT_DIR = _REPO_ROOT / "output"
_STATIC_DIR = _REPO_ROOT / "templates" / "static"
_DEPLOY_DIR = _REPO_ROOT / "_deploy"


def _run(cmd: list[str], cwd: Path = None):
    result = subprocess.run(cmd, cwd=cwd or _REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def deploy():
    """Push built site to gh-pages branch."""
    github_token = os.environ.get("GITHUB_TOKEN")

    # Prepare deploy directory
    if _DEPLOY_DIR.exists():
        shutil.rmtree(_DEPLOY_DIR)
    _DEPLOY_DIR.mkdir()

    # Copy index.html
    shutil.copy(_OUTPUT_DIR / "index.html", _DEPLOY_DIR / "index.html")

    # Copy static assets
    deploy_static = _DEPLOY_DIR / "static"
    if _STATIC_DIR.exists():
        shutil.copytree(_STATIC_DIR, deploy_static)

    # Write .nojekyll to prevent GitHub Pages from processing with Jekyll
    (_DEPLOY_DIR / ".nojekyll").touch()

    # Init a clean git repo in _deploy and force-push to gh-pages
    _run(["git", "init"], cwd=_DEPLOY_DIR)
    _run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=_DEPLOY_DIR)
    _run(["git", "config", "user.name", "github-actions[bot]"], cwd=_DEPLOY_DIR)
    _run(["git", "checkout", "-b", "gh-pages"], cwd=_DEPLOY_DIR)
    _run(["git", "add", "."], cwd=_DEPLOY_DIR)
    _run(["git", "commit", "-m", "deploy: update site"], cwd=_DEPLOY_DIR)

    remote_url = _run(["git", "remote", "get-url", "origin"])
    # Inject GITHUB_TOKEN into HTTPS URL so Actions bot can push without interactive auth
    if github_token:
        remote_url = remote_url.replace("https://", f"https://x-access-token:{github_token}@")
    _run(["git", "remote", "add", "origin", remote_url], cwd=_DEPLOY_DIR)
    _run(["git", "push", "origin", "gh-pages", "--force"], cwd=_DEPLOY_DIR)

    print("Deployed to gh-pages.")
