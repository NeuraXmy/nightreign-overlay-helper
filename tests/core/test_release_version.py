"""Version spelling may vary, but release contents must match the tag."""

import pytest
from scripts.validate_release_version import validate_tag


@pytest.mark.parametrize("tag", ["v1.0.0-dev.2", "1.0.0.dev2", "v1.0.0dev2"])
def test_prerelease_tags_normalize(tag):
    validate_tag(tag, "1.0.0.dev2")


@pytest.mark.parametrize("tag", ["v1.0.0", "v1.0.0-dev.1", "v2.0.0", "release"])
def test_mismatched_or_invalid_tags_fail(tag):
    with pytest.raises(ValueError):
        validate_tag(tag, "1.0.0.dev2")
