"""
Git identity synchronisation.

Resolves the correct git commit identity (user.name, user.email) from the
authenticated GitLab user and writes it to the per-repository git config.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .auth_broker import ProviderUser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known placeholder identities injected by the default Docker image
# ---------------------------------------------------------------------------

PLACEHOLDER_NAMES: set[str] = {
    "jovyan",
    "jovyan@localhost",
    "Jupyter User",
    "jupyter",
    "root",
    "unknown",
    "",
}

PLACEHOLDER_EMAIL_PATTERNS: list[str] = [
    r"jovyan",
    r"@localhost",
    r"@localdomain",
    r"user@example\.com",
    r"^$",
    r"noreply",
    r"no-reply",
    r"nobody",
]

_PLACEHOLDER_EMAIL_RE = re.compile(
    "|".join(PLACEHOLDER_EMAIL_PATTERNS), re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CommitIdentity:
    """The name and email to use for git commits."""

    name: str
    email: str


@dataclass
class ValidationResult:
    """Result of validating the current git identity against a GitLab user."""

    valid: bool
    current_name: str
    current_email: str
    is_placeholder: bool
    mismatch_details: str = ""


# ---------------------------------------------------------------------------
# IdentitySync
# ---------------------------------------------------------------------------


class IdentitySync:
    """
    Resolves and writes git commit identity for a repository.

    The canonical identity is the GitLab user's name and primary email,
    which is in turn sourced from Keycloak via OIDC — so it should match
    the `kubeflow-userid` header.
    """

    def resolve_commit_identity(
        self,
        jupyter_user_id: str,
        gitlab_user: "ProviderUser",
    ) -> CommitIdentity:
        """
        Determine the git commit identity to use.

        Preference order:
          1. GitLab user's name + email (most authoritative).
          2. Fall back to jupyter_user_id (email) if GitLab email is empty.
        """
        name = (gitlab_user.name or "").strip()
        email = (gitlab_user.email or "").strip()

        if not name:
            # Use the username if display name is empty
            name = gitlab_user.username or jupyter_user_id.split("@")[0]

        if not email:
            # Fall back to the Jupyter user ID (which is typically the email
            # from the kubeflow-userid header)
            email = jupyter_user_id

        return CommitIdentity(name=name, email=email)

    def write_git_identity(self, repo_path: str, identity: CommitIdentity) -> None:
        """
        Write user.name and user.email to the repository-local git config.

        Raises subprocess.CalledProcessError or FileNotFoundError if git is
        not available or repo_path is not a git repository.
        """
        repo = Path(repo_path)
        if not repo.exists():
            raise FileNotFoundError(f"Repository path does not exist: {repo_path}")

        # Verify it is a git repository
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ValueError(f"Not a git repository: {repo_path}")

        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", identity.name],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", identity.email],
            check=True,
            capture_output=True,
            text=True,
        )

        logger.info(
            "identity_sync: set git identity for %s → name=%r email=%r",
            repo_path,
            identity.name,
            identity.email,
        )

    def validate_git_identity(
        self, repo_path: str, gitlab_user: "ProviderUser"
    ) -> ValidationResult:
        """
        Compare the current git config identity for repo_path against the
        GitLab user's identity.

        Returns ValidationResult.valid=True if they match (case-insensitive
        email comparison).
        """
        current_name = ""
        current_email = ""

        try:
            current_name = subprocess.check_output(
                ["git", "-C", repo_path, "config", "user.name"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            pass

        try:
            current_email = subprocess.check_output(
                ["git", "-C", repo_path, "config", "user.email"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            pass

        is_placeholder = self.is_placeholder_identity(current_name, current_email)

        email_matches = current_email.lower() == (gitlab_user.email or "").lower()
        name_matches = current_name == gitlab_user.name

        if email_matches and name_matches:
            return ValidationResult(
                valid=True,
                current_name=current_name,
                current_email=current_email,
                is_placeholder=is_placeholder,
            )

        details_parts = []
        if not email_matches:
            details_parts.append(
                f"email mismatch: configured={current_email!r}, gitlab={gitlab_user.email!r}"
            )
        if not name_matches:
            details_parts.append(
                f"name mismatch: configured={current_name!r}, gitlab={gitlab_user.name!r}"
            )

        return ValidationResult(
            valid=False,
            current_name=current_name,
            current_email=current_email,
            is_placeholder=is_placeholder,
            mismatch_details="; ".join(details_parts),
        )

    def is_placeholder_identity(self, name: str, email: str) -> bool:
        """
        Return True if name/email look like a default/placeholder identity
        from the Jupyter Docker image (e.g., jovyan@localhost).

        Used to decide whether to prompt users to update their identity.
        """
        name_stripped = (name or "").strip()
        email_stripped = (email or "").strip()

        if name_stripped.lower() in {s.lower() for s in PLACEHOLDER_NAMES}:
            return True

        if _PLACEHOLDER_EMAIL_RE.search(email_stripped):
            return True

        return False
