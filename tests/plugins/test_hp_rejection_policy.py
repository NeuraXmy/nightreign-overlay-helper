"""Boundary coverage for HP refusal warnings and failures."""

import warnings

import pytest

from tests.support.hp_assertions import assert_rejection_duration, assert_rejection_ratio


@pytest.mark.parametrize("ratio", [0.0, 0.1999, 0.2])
def test_rejection_rate_at_or_below_twenty_percent_has_no_warning(ratio):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        assert_rejection_ratio(ratio, context="sample")
    assert not recorded


@pytest.mark.parametrize("ratio", [0.2001, 0.3, 0.5])
def test_rejection_rate_above_twenty_up_to_fifty_percent_warns_and_passes(ratio):
    with pytest.warns(UserWarning, match=r"sample: rejection ratio .*warning threshold 20%"):
        assert_rejection_ratio(ratio, context="sample")


@pytest.mark.parametrize("ratio", [0.5001, 1.0])
def test_rejection_rate_above_fifty_percent_fails(ratio):
    with pytest.raises(AssertionError, match=r"sample: rejection ratio .*failure limit 50%"):
        assert_rejection_ratio(ratio, context="sample")


@pytest.mark.parametrize("seconds", [0.0, 1.9999, 2.0])
def test_consecutive_rejection_at_or_below_two_seconds_has_no_warning(seconds):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        assert_rejection_duration(seconds, context="sample")
    assert not recorded


@pytest.mark.parametrize("seconds", [2.0001, 2.5, 3.0, 4.533333333333333, 5.0])
def test_consecutive_rejection_above_two_up_to_five_seconds_warns_and_passes(seconds):
    with pytest.warns(UserWarning, match=r"sample: consecutive rejection .*warning threshold 2s"):
        assert_rejection_duration(seconds, context="sample")


@pytest.mark.parametrize("seconds", [5.0001, 8.0])
def test_consecutive_rejection_above_five_seconds_fails(seconds):
    with pytest.raises(AssertionError, match=r"sample: consecutive rejection .*failure limit 5s"):
        assert_rejection_duration(seconds, context="sample")
