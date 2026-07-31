"""HTTP REST entry point (FastAPI), routed by resource.

External usage:
    from corti.entrypoints.api import create_app

    app = create_app()
"""

from .app import create_app as create_app

__all__ = ["create_app"]
