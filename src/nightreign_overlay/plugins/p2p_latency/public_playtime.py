"""Best-effort parsing of Steam's English public profile recent-game cards."""

import re
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import urlsplit


class _ProfileParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.divs: list[set[str]] = []
        self.target = False
        self.details: list[str] = []
        self.minutes: list[int] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            classes = set(attrs.get("class", "").split())
            self.divs.append(classes)
            if "recent_game" in classes:
                self.target = False
                self.details = []
        if tag == "a" and any("game_info" in c for c in self.divs):
            url = urlsplit(attrs.get("href", ""))
            if url.hostname == "steamcommunity.com" and url.path.rstrip("/") == "/app/2622380":
                self.target = True

    def handle_data(self, data):
        if any("recent_game" in c for c in self.divs) and any("game_info_details" in c for c in self.divs):
            self.details.append(data)

    def handle_endtag(self, tag):
        if tag != "div" or not self.divs:
            return
        classes = self.divs.pop()
        if "recent_game" in classes and self.target:
            match = re.search(
                r"(?<![\d.,])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s+hrs? on record\b",
                " ".join(self.details),
            )
            if match:
                self.minutes.append(int(Decimal(match[1].replace(",", "")) * 60))


def parse_public_playtime(raw_data: bytes) -> int | None:
    """Return displayed (rounded by Steam) total minutes, never assume missing = 0."""
    parser = _ProfileParser()
    parser.feed(raw_data.decode("utf-8"))
    parser.close()
    return parser.minutes[0] if len(parser.minutes) == 1 else None
