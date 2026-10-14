"""Pure stronghold-constraint matching for manual map filtering (no Qt)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from PIL import Image

from nightreign_overlay.plugins.map_detect.detector import (
    CTYPE_SUBICON_MAP,
    SUBICON_IMAGES,
    Attribute,
    Condition,
    PoiCategoryInfo,
    build_poi_categories,
    get_poi_key,
    load_default_map_info,
)
from nightreign_overlay.plugins.map_detect.map_info import MapInfo, MapPattern, Position

EMPTY = 0  # Base group meaning "no stronghold"; matches the detector's empty POI category.
NONE: None = None  # Explicitly require the stronghold to have no badge.

Subicon = Attribute | Condition | None


class Unset(Enum):
    UNSET = "unset"


UNSET = Unset.UNSET  # Badge not chosen: any badge (or none) matches the base.


@dataclass(frozen=True)
class PoiChoice:
    base: int  # Base-icon group, or EMPTY.
    subicon: Subicon | Unset = UNSET

    def accepts(self, value: tuple[int, Subicon]) -> bool:
        base, subicon = value
        return base == self.base and (self.subicon is UNSET or subicon == self.subicon)


class ManualFilterCatalog:
    """Stronghold values per map pattern, with identical base icons merged into one group."""

    def __init__(
        self,
        info: MapInfo,
        all_poi_images: Mapping[int, Image.Image],
        poi_cate_info: Mapping[int, PoiCategoryInfo],
    ) -> None:
        self.info = info
        self.poi_cate_info = poi_cate_info
        # Same rule as the detector's pattern scoring: non-POI constructions count as empty.
        self._poi_types = frozenset(all_poi_images)
        self._group_of: dict[int, int] = {0: EMPTY}
        groups: dict[bytes, int] = {}
        for key in sorted(k for k in poi_cate_info if k != 0):
            image = poi_cate_info[key].base_image
            digest = hashlib.md5(repr(image.size).encode() + image.tobytes()).digest()
            self._group_of[key] = groups.setdefault(digest, key)
        self._pools: dict[tuple[int, int | None], list[MapPattern]] = {}

    @classmethod
    def load(cls, language: str) -> ManualFilterCatalog:
        info = load_default_map_info(language)
        all_poi_images, poi_cate_info = build_poi_categories(info)
        return cls(info, all_poi_images, poi_cate_info)

    # Values and choices -------------------------------------------------------------------------

    def group_of(self, poi_key: int) -> int:
        return self._group_of[poi_key]

    def groups(self) -> list[int]:
        """Every non-empty base group, by group id."""
        return sorted({group for group in self._group_of.values() if group != EMPTY})

    def base_image(self, group: int) -> Image.Image:
        return self.poi_cate_info[group].base_image

    @staticmethod
    def subicon_image(subicon: Attribute | Condition) -> Image.Image:
        return SUBICON_IMAGES[subicon]

    def value(self, pattern: MapPattern, pos: Position) -> tuple[int, Subicon]:
        construct = pattern.pos_constructions.get(pos)
        ctype = construct.type if construct is not None else 0
        if ctype not in self._poi_types:
            ctype = 0
        return self.choice_from_ctype(ctype).base, CTYPE_SUBICON_MAP.get(ctype)

    def choice_from_ctype(self, ctype: int) -> PoiChoice:
        """Explicit choice equivalent to a recognized construct type."""
        if ctype == 0:
            return PoiChoice(EMPTY, None)
        poi_key = get_poi_key(ctype)
        if poi_key is None or poi_key not in self._group_of:
            return PoiChoice(EMPTY, None)
        return PoiChoice(self._group_of[poi_key], CTYPE_SUBICON_MAP.get(ctype))

    # Queries ------------------------------------------------------------------------------------

    def _pool(self, earth_shifting: int, nightlord: int | None) -> list[MapPattern]:
        key = (earth_shifting, nightlord)
        if key not in self._pools:
            self._pools[key] = [
                pattern
                for pattern in self.info.patterns
                if pattern.earth_shifting == earth_shifting
                and (nightlord is None or pattern.nightlord == nightlord)
            ]
        return self._pools[key]

    def positions(self, earth_shifting: int, nightlord: int | None) -> list[Position]:
        nightlords = self.info.all_nightlords if nightlord is None else (nightlord,)
        positions: set[Position] = set()
        for nl in nightlords:
            positions.update(self.info.all_poi_pos.get((earth_shifting, nl), set()))
        return sorted(positions)

    def all_positions(self) -> list[Position]:
        return sorted({pos for positions in self.info.all_poi_pos.values() for pos in positions})

    def candidates(
        self,
        earth_shifting: int,
        nightlord: int | None,
        explicit: Mapping[Position, PoiChoice],
        exclude: Position | None = None,
    ) -> list[MapPattern]:
        constraints = [(pos, choice) for pos, choice in explicit.items() if pos != exclude]
        return [
            pattern
            for pattern in self._pool(earth_shifting, nightlord)
            if all(choice.accepts(self.value(pattern, pos)) for pos, choice in constraints)
        ]

    def base_options(
        self,
        earth_shifting: int,
        nightlord: int | None,
        explicit: Mapping[Position, PoiChoice],
        pos: Position,
    ) -> list[int]:
        """Bases still possible at ``pos`` ignoring its own choice; EMPTY first when possible."""
        bases = {
            self.value(pattern, pos)[0]
            for pattern in self.candidates(earth_shifting, nightlord, explicit, exclude=pos)
        }
        return sorted(bases, key=lambda base: (base != EMPTY, base))

    def subicon_options(
        self,
        earth_shifting: int,
        nightlord: int | None,
        explicit: Mapping[Position, PoiChoice],
        pos: Position,
        base: int,
    ) -> list[Subicon]:
        """Badges still possible for ``base`` at ``pos``; ``None`` (no badge) first when possible."""
        subicons = {
            subicon
            for pattern in self.candidates(earth_shifting, nightlord, explicit, exclude=pos)
            for value_base, subicon in [self.value(pattern, pos)]
            if value_base == base
        }
        return sorted(subicons, key=_subicon_order)

    def inferred(
        self,
        candidates: Iterable[MapPattern],
        positions: Iterable[Position],
        explicit: Mapping[Position, PoiChoice],
    ) -> dict[Position, PoiChoice]:
        """Display-only values every candidate agrees on; never feed these back as constraints.

        Unset positions get a unique base (and its badge when that is unique too); explicit positions
        whose badge is unset get a unique badge.
        """
        candidates = list(candidates)
        if not candidates:
            return {}
        result: dict[Position, PoiChoice] = {}
        for pos in positions:
            choice = explicit.get(pos)
            if choice is not None and choice.subicon is not UNSET:
                continue
            values = {self.value(pattern, pos) for pattern in candidates}
            bases = {base for base, _ in values}
            if len(bases) != 1:
                continue
            base = bases.pop()
            subicons = {subicon for _, subicon in values}
            subicon = subicons.pop() if len(subicons) == 1 else UNSET
            if choice is None or subicon is not UNSET:
                result[pos] = PoiChoice(base, subicon)
        return result


def _subicon_order(subicon: Subicon) -> tuple[int, int]:
    if subicon is None:
        return (0, 0)
    return (1 if isinstance(subicon, Attribute) else 2, subicon.value)
