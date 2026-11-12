"""Environment handling that MUST run before any ``app.*`` import (DESIGN 2.3).

Steps, in order:
1. ``load_dotenv()`` (existing environment variables win, same call as the core).
2. Demo mode: point the SDK at the stub and override the key with ``sk-demo-stub``
   so a real key is never sent to the stub.
3. Otherwise, with no key: set the placeholder ``not-configured`` so the core can be
   imported; Studio routes refuse to use it (503 openai_not_configured).
4. (done by ``studio.core_adapter``) import the core.

The outcome is recorded in ``state``; routes read it at call time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from studio.settings import DEFAULT_DATABASE_URL, DEFAULT_STUB_URL, env_bool

DEMO_KEY = "sk-demo-stub"
PLACEHOLDER_KEY = "not-configured"


@dataclass
class BootstrapState:
    demo_mode: bool = False
    openai_configured: bool = False
    database_url_defaulted: bool = False


state = BootstrapState()


def _run() -> None:
    load_dotenv()

    if not (os.environ.get("DATABASE_URL") or "").strip():
        os.environ["DATABASE_URL"] = DEFAULT_DATABASE_URL
        state.database_url_defaulted = True

    if env_bool("STUDIO_DEMO_MODE"):
        state.demo_mode = True
        os.environ["OPENAI_BASE_URL"] = (os.environ.get("STUDIO_STUB_URL") or DEFAULT_STUB_URL).strip()
        os.environ["OPENAI_API_KEY"] = DEMO_KEY
        state.openai_configured = True
        return

    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key or key == PLACEHOLDER_KEY:
        os.environ["OPENAI_API_KEY"] = PLACEHOLDER_KEY
        state.openai_configured = False
    else:
        state.openai_configured = True


_run()
