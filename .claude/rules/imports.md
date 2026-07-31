---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Imports rule

- **`from __future__ import annotations`** is the first import in every module.
- **Import order** (ruff `I` enforces, `make format` fixes): stdlib → third-party
  → first-party (`everalgo`, then `corti`). One group per blank-line-separated block.
- **Absolute imports** for cross-package references (`from corti.memory import ...`).
  Relative imports (`from .models import ...`) only **within** a package, typically
  in its `__init__.py`.
- **`TYPE_CHECKING` guard** for import cycles and type-only imports:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from corti.config import Settings
  ```
- Never import a private internal across a package boundary — respect the
  `import-linter` contracts (see [architecture.md](architecture.md)).
