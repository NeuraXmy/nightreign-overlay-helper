"""Lightweight tests for manual stronghold matching rules."""

from __future__ import annotations

from nightreign_overlay.plugins.map_detect.manual_catalog import (
    UNSET,
    ManualFilterCatalog,
    PoiChoice,
)


def _catalog() -> ManualFilterCatalog:
    return ManualFilterCatalog.load("zh_CN")


def test_identical_base_icons_are_merged() -> None:
    catalog = _catalog()
    assert catalog.group_of(511) == catalog.group_of(40) == 40
    assert catalog.group_of(525) == catalog.group_of(34) == 34
    assert catalog.group_of(524) == catalog.group_of(38) == 38
    assert catalog.group_of(510) == catalog.group_of(41) == 41


def test_base_only_constraint_accepts_every_badge_and_impossible_base_matches_nothing() -> None:
    catalog = _catalog()
    found = None
    for earth_shifting in catalog.info.all_earth_shiftings:
        for nightlord in catalog.info.all_nightlords:
            pool = catalog.candidates(earth_shifting, nightlord, {})
            for pos in catalog.positions(earth_shifting, nightlord):
                by_base: dict[int, set[object]] = {}
                for pattern in pool:
                    base, subicon = catalog.value(pattern, pos)
                    by_base.setdefault(base, set()).add(subicon)
                for base, subicons in by_base.items():
                    if base and len(subicons) > 1:
                        found = earth_shifting, nightlord, pos, base, subicons
                        break
                if found:
                    break
            if found:
                break
        if found:
            break

    assert found is not None
    earth_shifting, nightlord, pos, base, possible_subicons = found
    base_only = catalog.candidates(earth_shifting, nightlord, {pos: PoiChoice(base, UNSET)})
    assert {catalog.value(pattern, pos)[1] for pattern in base_only} == possible_subicons
    assert catalog.candidates(earth_shifting, nightlord, {pos: PoiChoice(999999)}) == []


def test_inference_is_display_only_and_options_ignore_the_positions_own_constraint() -> None:
    catalog = _catalog()
    pattern = catalog.info.patterns[0]
    positions = catalog.positions(pattern.earth_shifting, pattern.nightlord)
    inferred = catalog.inferred([pattern], positions, {})
    assert inferred
    for pos, choice in inferred.items():
        assert choice.accepts(catalog.value(pattern, pos))

    pos = positions[0]
    possible = catalog.base_options(pattern.earth_shifting, pattern.nightlord, {}, pos)
    # An impossible current choice does not suppress valid replacement options at the same position.
    assert (
        catalog.base_options(
            pattern.earth_shifting,
            pattern.nightlord,
            {pos: PoiChoice(999999)},
            pos,
        )
        == possible
    )
