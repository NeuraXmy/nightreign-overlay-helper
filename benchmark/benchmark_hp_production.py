"""Full HP production-video benchmark; run explicitly after HP detection changes."""

import pytest
from tests.support.hp_assertions import assert_rejection_duration, assert_rejection_ratio
from tests.support.hp_production_evaluation import evaluate_production, production_labels

pytestmark = pytest.mark.benchmark


@pytest.fixture(scope="module", params=production_labels(), ids=lambda label: label["id"])
def production_report(request):
    return evaluate_production(request.param)


def test_all_sampling_rates_have_no_errors_and_bounded_refusal(production_report):
    for report in production_report["continuous"]:
        assert report["incorrect"] == 0, report
        assert_rejection_ratio(
            report["rejection_ratio"],
            context=f"{production_report['id']} interval={report['interval_seconds']}s",
        )
        assert_rejection_duration(
            report["longest_rejection_seconds"],
            context=f"{production_report['id']} interval={report['interval_seconds']}s",
        )


def test_every_independent_start_produces_fresh_correct_output(production_report):
    summary = production_report["cold_start_summary"]
    assert summary["windows"] > 0
    assert summary["incorrect"] == 0, summary
    assert summary["windows_without_output"] == 0, summary
    assert summary["slowest_first_output_seconds"] < 2.5, summary
    windows = production_report["cold_starts"]
    # Aggregate refusal includes the compulsory confirmation delay. Individual
    # windows still have separate limits on consecutive dropouts below.
    assert_rejection_ratio(
        sum(window["rejected"] for window in windows) / sum(window["evaluated"] for window in windows),
        context=f"{production_report['id']} cold starts (aggregate)",
    )
    for window in production_report["cold_starts"]:
        assert_rejection_duration(
            window["longest_rejection_seconds"],
            context=f"{production_report['id']} cold start at {window['start_seconds']}s",
        )
