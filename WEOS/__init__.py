"""WEOS — Window Engineering Operating System.

Design • Calculate • Manufacture • Quote

Manufacturing OS for windows, doors, pergolas, railings, facades.
API JSON is the product; CAD/DXF is optional factory export only.
"""

import os

__version__ = "2.0.0"
BUILD_REVISION = (
    os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    or os.environ.get("GIT_COMMIT_SHA")
    or os.environ.get("SOURCE_COMMIT")
    or "local"
)
TAGLINE = "Design • Calculate • Manufacture • Quote"
