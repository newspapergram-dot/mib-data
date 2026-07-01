import sys
from pathlib import Path

# Garantisce che `orchestrator`, `post_mortem` e `agents.*` siano importabili
# indipendentemente da come viene invocato pytest (rootdir vs cwd).
sys.path.insert(0, str(Path(__file__).resolve().parent))
