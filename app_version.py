"""
Total Commander Clone - Application version (single source of truth)
Bump APP_VERSION here and record changes in CHANGELOG.md for every release.
"""

# ------------------------------------------------------------
# Public constants
# ------------------------------------------------------------
APP_NAME = "Total Commander Clone"
APP_VERSION = "0.5.0"


def getWindowTitle():
    """Title bar text including version."""
    return f"{APP_NAME} — {APP_VERSION}"
