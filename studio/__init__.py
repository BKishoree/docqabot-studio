"""DocQABot Studio: application layer around the frozen core in ``app/``.

This package's ``__init__`` must stay free of side effects: ``studio.stub`` is
imported by tests without touching the environment or the core.
"""

__version__ = "1.0.0"
