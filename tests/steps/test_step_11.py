"""Step 11 checkpoint: observe, evaluate, and harden."""

import pytest

from campus_copilot import config
from campus_copilot.evaluation.runner import run_eval
from campus_copilot.observability.report import build_report, load_spans

pytestmark = pytest.mark.step11


def test_evaluation_report_and_controls(adversarial_env):
    settings = config.get_settings(config.step_profile_name(11), {"app.force_offline": True, "apis.live": False})
    run = run_eval(settings, echo=None)
    report = run.report()
    assert "By category:" in report and "By language:" in report and "| km |" in report
    adversarial = [r for r in run.rows if r["category"] == "adversarial" and not r.get("skipped")]
    assert adversarial and all(r["checks"]["control"] for r in adversarial), [
        r["id"] for r in adversarial if not r["checks"]["control"]]
    trace = build_report(load_spans(), settings.profile.get("prices"))
    assert trace["turns"] >= len(run.rows) and trace["nodes"]["guard_and_route"]["n"] >= len(run.rows)
