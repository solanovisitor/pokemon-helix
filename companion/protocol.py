"""Strict, bounded line protocol. No executable payloads or gameplay effects."""
from __future__ import annotations

from dataclasses import dataclass
import re
import textwrap
import unicodedata

PROTOCOL = "GBA1"
MAX_WIRE = 640
MAX_TEXT = 239
LINE_WIDTH = 30  # All whitelisted Latin glyphs are <=6 px; normal font window=208px.
MAX_LINES = 4
CHARMAP = {" ": 0, "!": 0xAB, "?": 0xAC, ".": 0xAD, "-": 0xAE,
           "'": 0xB4, ",": 0xB8, "/": 0xBA, ":": 0xF0}
CHARMAP.update({chr(48 + i): 0xA1 + i for i in range(10)})
CHARMAP.update({chr(65 + i): 0xBB + i for i in range(26)})
CHARMAP.update({chr(97 + i): 0xD5 + i for i in range(26)})
ALLOWED_BYTES = frozenset(CHARMAP.values()) | {0xFE, 0xFB}


class ProtocolError(ValueError):
    """Malformed or unsupported peer input; safe to reject without logging data."""


@dataclass(frozen=True)
class Request:
    session: str
    epoch: int
    request: int
    npc: int
    motivation: int
    quest: int

    @property
    def key(self) -> tuple[str, int, int]:
        return self.session, self.epoch, self.request

    def identity(self) -> str:
        return "|".join(str(v) for v in (self.session, self.epoch, self.request,
                                        self.npc, self.motivation, self.quest))

    def wire(self, kind: str = "REQ") -> bytes:
        return f"{PROTOCOL}|{kind}|{self.identity()}\n".encode("ascii")


def parse_request(line: bytes) -> tuple[str, Request]:
    if not line.endswith(b"\n") or len(line) > MAX_WIRE:
        raise ProtocolError("invalid framing")
    try:
        fields = line[:-1].decode("ascii").split("|")
    except UnicodeDecodeError as exc:
        raise ProtocolError("non-ascii frame") from exc
    if len(fields) != 8 or fields[0] != PROTOCOL or fields[1] not in {"REQ", "CANCEL", "ACK"}:
        raise ProtocolError("invalid envelope")
    session, *numbers = fields[2:]
    if not re.fullmatch(r"[a-f0-9]{16,64}-[0-9]{1,10}", session):
        raise ProtocolError("invalid session")
    if any(not re.fullmatch(r"[0-9]{1,10}", value) for value in numbers):
        raise ProtocolError("invalid integer")
    epoch, sequence, npc, motivation, quest = map(int, numbers)
    if not (1 <= epoch <= 0xFFFFFFFF and 1 <= sequence <= 0xFFFFFFFF
            and npc in {1, 2, 3, 4} and motivation in {0, 1, 2} and quest in {0, 1, 2, 3}):
        raise ProtocolError("unsupported state")
    if quest > 0 and motivation == 0:
        raise ProtocolError("quest without motivation")
    return fields[1], Request(session, epoch, sequence, npc, motivation, quest)


def validate_encoded(data: bytes) -> None:
    if not 1 <= len(data) <= MAX_TEXT or any(v not in ALLOWED_BYTES for v in data):
        raise ProtocolError("invalid encoded text")
    # Only the wrapper may insert controls: one newline per page, two pages total.
    pages = data.split(b"\xfb")
    if len(pages) > 2:
        raise ProtocolError("too many pages")
    for page in pages:
        lines = page.split(b"\xfe")
        if len(lines) > 2 or any(not 1 <= len(line) <= LINE_WIDTH for line in lines):
            raise ProtocolError("invalid lines")


def encode_text(text: str) -> bytes:
    if not isinstance(text, str) or not 1 <= len(text) <= 1000:
        raise ProtocolError("invalid model text")
    # Never accept game escape syntax. Unsupported punctuation is inert whitespace.
    text = text.translate(str.maketrans({"’": "'", "‘": "'", "—": "-", "–": "-", "…": "..."}))
    text = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in text if not unicodedata.combining(c))
    plain = " ".join("".join(c if c in CHARMAP else " " for c in plain).split())
    if not plain:
        raise ProtocolError("empty supported text")
    lines = textwrap.wrap(plain, width=LINE_WIDTH, break_long_words=True, break_on_hyphens=False)
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines[-1] = lines[-1][:LINE_WIDTH - 3].rstrip() + "..."
    result = bytearray()
    for index, line in enumerate(lines):
        if index:
            result.append(0xFB if index == 2 else 0xFE)
        result.extend(CHARMAP[c] for c in line)
    validate_encoded(bytes(result))
    return bytes(result)


def response_wire(request: Request, text: bytes | None = None) -> bytes:
    if text is not None:
        validate_encoded(text)
    status = "OK" if text is not None else "ERROR"
    return f"{PROTOCOL}|{status}|{request.identity()}|{text.hex() if text else ''}\n".encode("ascii")
