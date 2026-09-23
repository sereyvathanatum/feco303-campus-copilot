"""Export the compiled LangGraph as Mermaid: the baseline for docs/architecture.md and one diagram per build step.

Offline and self-contained: uses a temporary runs folder, so no local state is touched.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs" / "build-path" / "diagrams"


def main() -> int:
    os.environ["COPILOT_RUNS_DIR"] = tempfile.mkdtemp(prefix="graphs-")
    from campus_copilot import config
    from campus_copilot.graph.build import Copilot
    from campus_copilot.graph.capabilities import step_label

    OUT.mkdir(parents=True, exist_ok=True)
    offline = {"app.force_offline": True, "apis.live": False, "tools.transport": "inprocess"}
    diagrams = {}
    for step in range(5, 13):
        profile = config.step_profile_name(step)
        copilot = Copilot(config.get_settings(profile, offline))
        diagrams[step] = copilot.mermaid()
        label = step_label(copilot.settings.profile)
        (OUT / f"step-{step:02d}.md").write_text(
            f"# {label}\n\nThe compiled graph at this step (exported by `scripts/export_graphs.py`).\n\n"
            f"```mermaid\n{diagrams[step]}\n```\n", encoding="utf-8", newline="\n")
        copilot.close()
        print(f"wrote docs/build-path/diagrams/step-{step:02d}.md")
    baseline = Copilot(config.get_settings("baseline", offline))
    (OUT / "baseline.mmd").write_text(baseline.mermaid() + "\n", encoding="utf-8", newline="\n")
    baseline.close()
    print("wrote docs/build-path/diagrams/baseline.mmd")
    return 0


if __name__ == "__main__":
    sys.exit(main())
