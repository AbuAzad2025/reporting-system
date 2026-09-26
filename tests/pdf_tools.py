"""Stdlib-only PDF inspector: ASCII85 + Flate decoder and drawn-text extractor.

ReportLab (the engine behind every Azadexa document) writes page content as
``/Filter [/ASCII85Decode /FlateDecode]`` streams, so content-level assertions
need no third-party parser:

* :func:`decode_stream` reverses ASCII85 + Flate (and bare Flate) filters;
* :class:`PdfDocument` walks the page tree, cross-checks the xref table,
  trailer and catalog, and returns the text *actually drawn* per page.

Text fidelity contract
----------------------
The Arabic faces are embedded as subset TrueType fonts and the Arabic strings
are shaped/bidi-reordered into presentation forms, so they must never be
asserted on. Latin is safe and is what the helpers promote:

* subset TrueType keeps ASCII identity -- codes ``0x20..0x7F`` map to
  themselves in the font ``/ToUnicode`` CMap, so digits, serials, money
  strings and file names come out verbatim;
* the base-14 ``Helvetica``/``Helvetica-Bold`` faces use ``WinAnsiEncoding``
  and are decoded as cp1252, which also recovers U+2014 EM DASH.

:attr:`PdfDocument.latin_text` is therefore the projection tests should assert
on, while :attr:`PdfDocument.text` is the full decoded text.
"""
import base64
import re
import zlib

__all__ = ["PdfDocument", "decode_stream", "extract_text", "latin_text"]

# --------------------------------------------------------------- filters
_ASCII85_END = b"~>"


def _ascii85_decode(payload: bytes) -> bytes:
    """Undo an ASCII85 filter body (ReportLab omits the ``<~`` prologue)."""
    data = re.sub(rb"[\s\x00]", b"", payload)
    if data.startswith(b"<~"):
        data = data[2:]
    if data.endswith(_ASCII85_END):
        data = data[:-2]
    return base64.a85decode(data)


def _flate_decode(payload: bytes) -> bytes:
    """Inflate a zlib/deflate stream, tolerating a stray leading byte."""
    try:
        return zlib.decompress(payload)
    except zlib.error:
        return zlib.decompressobj().decompress(payload)


_FILTERS = {
    b"ASCII85Decode": _ascii85_decode,
    b"ASCIIHexDecode": lambda d: bytes.fromhex(
        re.sub(rb"[\s\x00>]", b"", d).decode("ascii")),
    b"FlateDecode": _flate_decode,
}


def decode_stream(filters: bytes, payload: bytes) -> bytes:
    """Apply the ``/Filter`` chain of a stream object, in declared order.

    ``filters`` is the raw ``/Filter`` value (``/FlateDecode`` or
    ``[/ASCII85Decode /FlateDecode]``); unknown filters are ignored so an
    image-only stream never breaks text extraction.
    """
    names = re.findall(rb"/([A-Za-z0-9]+)", filters)
    data = payload
    for name in names:
        fn = _FILTERS.get(name)
        if fn is None:
            continue
        try:
            data = fn(data)
        except Exception:
            return b""
    return data


# --------------------------------------------------------------- objects
_OBJ_HEADER = re.compile(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b")
_STREAM_KW = re.compile(rb"stream(\r\n|\r|\n)")
_LENGTH = re.compile(rb"/Length\s+(\d+)\s")


def _scan_objects(data: bytes):
    """Yield ``(number, dict_bytes, payload)`` for every indirect object.

    A sequential scan is used rather than a global regex so that binary
    stream payloads (embedded TrueType programs) can never be mistaken for
    object headers: after a stream the cursor resumes past ``endstream``.
    """
    objects = {}
    pos = 0
    end = len(data)
    while pos < end:
        head = _OBJ_HEADER.search(data, pos)
        if head is None:
            break
        body = head.end()
        nxt = _OBJ_HEADER.search(data, body)
        limit = nxt.start() if nxt else end
        stream = _STREAM_KW.search(data, body, limit)
        if stream is not None and _LENGTH.search(data, body, stream.start()):
            length = int(_LENGTH.search(data, body, stream.start()).group(1))
            payload = data[stream.end():stream.end() + length]
            stop = stream.end() + length
            close = data.find(b"endstream", stop, stop + 32)
            pos = close + 9 if close > 0 else stop
            objects[int(head.group(1))] = (data[body:stream.start()], payload)
        else:
            close = data.find(b"endobj", body, limit)
            stop = close if close > 0 else limit
            pos = stop + 6
            objects[int(head.group(1))] = (data[body:stop], None)
    return objects


# --------------------------------------------------------------- tokenizer
_WHITESPACE = b"\x00\t\n\x0c\r "
_DELIMITERS = b"()<>[]{}/%'\""
_STR_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b",
                b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}


def _read_literal(data: bytes, start: int):
    """Read a ``(...)`` string body with balanced parens; skip escapes."""
    out = bytearray()
    depth = 1
    i = start + 1
    end = len(data)
    while i < end:
        ch = data[i:i + 1]
        if ch == b"\\":
            nxt = data[i + 1:i + 2]
            if nxt in _STR_ESCAPES:
                out += _STR_ESCAPES[nxt]
                i += 2
            elif nxt.isdigit():
                digits = re.match(rb"[0-7]{1,3}", data[i + 1:i + 4])
                out.append(int(digits.group(0), 8) & 0xFF)
                i += 1 + len(digits.group(0))
            elif nxt in (b"\n", b"\r"):
                i += 2
            else:
                out += nxt
                i += 2
        elif ch == b"(":
            depth += 1
            out += ch
            i += 1
        elif ch == b")":
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
            out += ch
            i += 1
        else:
            out += ch
            i += 1
    return bytes(out), end


def _read_name(data: bytes, start: int):
    """Read a ``/Name`` token, resolving ``#xx`` hex escapes."""
    i = start + 1
    end = len(data)
    while i < end and data[i:i + 1] not in _WHITESPACE and \
            data[i:i + 1] not in _DELIMITERS:
        i += 1
    raw = data[start + 1:i]
    return re.sub(rb"#([0-9A-Fa-f]{2})",
                  lambda m: bytes([int(m.group(1), 16)]), raw), i


def tokenize(stream: bytes):
    """Yield ``(kind, value)`` tokens of a content stream.

    Kinds: ``str`` (bytes), ``name`` (bytes), ``num`` (float), ``op`` (bytes)
    and the array markers ``open``/``close``.
    """
    i = 0
    end = len(stream)
    while i < end:
        ch = stream[i:i + 1]
        if ch in _WHITESPACE:
            i += 1
        elif ch == b"%":
            stop = stream.find(b"\n", i)
            i = end if stop < 0 else stop + 1
        elif ch == b"(":
            text, i = _read_literal(stream, i)
            yield "str", text
        elif ch == b"<":
            if stream[i + 1:i + 2] == b"<":
                i = stream.find(b">>", i) + 2
                continue
            stop = stream.find(b">", i)
            digits = re.sub(rb"[\s\x00]", b"", stream[i + 1:stop])
            if len(digits) % 2:
                digits += b"0"
            yield "str", bytes.fromhex(digits.decode("ascii", "replace"))
            i = stop + 1
        elif ch == b"/":
            name, i = _read_name(stream, i)
            yield "name", name
        elif ch in b"'\"":
            yield "op", ch
            i += 1
        elif ch == b"[":
            yield "open", None
            i += 1
        elif ch == b"]":
            yield "close", None
            i += 1
        elif ch in b"><":
            i += 1
        else:
            stop = i
            while stop < end and stream[stop:stop + 1] not in _WHITESPACE \
                    and stream[stop:stop + 1] not in _DELIMITERS:
                stop += 1
            word = stream[i:stop]
            i = stop
            if _NUMBER.fullmatch(word):
                yield "num", float(word)
            else:
                yield "op", word


_NUMBER = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)$")
_SHOW = {b"Tj", b"TJ", b"'", b'"'}


# --------------------------------------------------------------- ToUnicode
def _utf16(hex_text: bytes) -> str:
    raw = bytes.fromhex(hex_text.decode("ascii", "replace"))
    if len(raw) % 2:
        raw += b"\x00"
    return raw.decode("utf-16-be", "replace")


def _parse_cmap(data: bytes):
    """Return ``({code: text}, code_byte_length)`` from a /ToUnicode CMap."""
    codes = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            codes[int(src, 16)] = _utf16(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        pattern = (rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*"
                   rb"(\[[^\]]*\]|<[0-9A-Fa-f]+>)")
        for low, high, dest in re.findall(pattern, block):
            first, last = int(low, 16), int(high, 16)
            if dest.startswith(b"["):
                items = re.findall(rb"<([0-9A-Fa-f]+)>", dest)
                for offset, item in enumerate(items):
                    codes[first + offset] = _utf16(item)
            else:
                units = [_utf16(dest[1:-1])]
                start = int(dest.strip(b"<>"), 16)
                width = len(dest.strip(b"<>")) // 4
                for offset in range(last - first + 1):
                    tail = start + offset
                    head = units[0][:-width] if width else ""
                    codes[first + offset] = head + chr(tail)
    width = 1
    spaces = re.search(rb"begincodespacerange(.*?)endcodespacerange",
                       data, re.S)
    if spaces:
        lengths = [len(low) // 2
                   for low, _ in re.findall(
                       rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>",
                       spaces.group(1))]
        if lengths:
            width = min(lengths)
    return codes, width


class _Font:
    """A font resource: subset code -> text map, or None for base-14."""

    __slots__ = ("name", "codes", "width")

    def __init__(self, name, codes=None, width=1):
        self.name = name
        self.codes = codes
        self.width = width

    def decode(self, raw: bytes) -> str:
        if self.codes is None:
            return raw.decode("cp1252", "replace")
        out = []
        step = self.width
        for offset in range(0, len(raw) - step + 1, step):
            out.append(self.codes.get(
                int.from_bytes(raw[offset:offset + step], "big"), ""))
        return "".join(c for c in out if c >= " " and c != "\x7f")


# --------------------------------------------------------------- document
_REF = re.compile(rb"/([A-Za-z0-9]+)\s+(\d+)\s+\d+\s+R")
_HAS_LATIN = re.compile(r"[A-Za-z0-9]")


class PdfDocument:
    """Parsed view over a rendered PDF: validity, page tree and drawn text."""

    def __init__(self, data: bytes):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("PdfDocument needs raw PDF bytes")
        self.data = bytes(data)
        self.objects = _scan_objects(self.data)
        self.problems = self._validate()
        self._fonts = self._collect_fonts()
        self._pages = self._collect_pages()
        self.page_texts = [self._text_of(page) for page in self._pages]

    # -- structure ------------------------------------------------------
    def dict_of(self, number: int) -> bytes:
        """Raw dictionary bytes of an indirect object (``b""`` if absent)."""
        entry = self.objects.get(int(number))
        return entry[0] if entry else b""

    def payload_of(self, number: int) -> bytes:
        """Decoded stream payload of an indirect object."""
        entry = self.objects.get(int(number))
        if not entry or entry[1] is None:
            return b""
        return decode_stream(_filter_of(entry[0]), entry[1])

    @property
    def page_count(self) -> int:
        return len(self._pages)

    @property
    def is_valid(self) -> bool:
        return not self.problems

    @property
    def content_streams(self):
        return [self.payload_of(ref) for page in self._pages
                for ref in page["contents"]]

    @property
    def metadata(self) -> dict:
        """Decoded ``/Info`` string entries (title, author, ...)."""
        trailer = self._trailer()
        match = _REF.search(trailer, trailer.find(b"/Info"))
        body = self.dict_of(int(match.group(2))) if match else b""
        out = {}
        for key, raw in re.findall(
                rb"/([A-Za-z0-9]+)\s*(\((?:\\.|[^\\()])*\))", body):
            text, _ = _read_literal(raw, 0)
            out[key.decode("ascii")] = text.decode("cp1252", "replace")
        return out

    @property
    def fonts(self):
        return {name: font.name for name, font in self._fonts.items()}

    @property
    def image_count(self) -> int:
        """Number of embedded raster image XObjects (photos, brand logo)."""
        return sum(1 for body, _payload in self.objects.values()
                   if b"/Subtype /Image" in body
                   or b"/Subtype/Image" in body)

    # -- text -----------------------------------------------------------
    @property
    def text_runs(self):
        return [run for page in self.page_texts for run in page]

    @property
    def text(self) -> str:
        return "\n".join(self.text_runs)

    @property
    def latin_text(self) -> str:
        """Only the drawn runs that carry Latin letters or digits.

        Money strings and counters are pure digits, so the filter keys on
        ``[A-Za-z0-9]``: that keeps money/serial/date evidence and drops the
        Arabic presentation forms, which must never be asserted on.
        """
        return "\n".join(r for r in self.text_runs if _HAS_LATIN.search(r))

    def page_text(self, number: int) -> str:
        return "\n".join(self.page_texts[number - 1])

    # -- internals ------------------------------------------------------
    def _trailer(self) -> bytes:
        pos = self.data.rfind(b"trailer")
        return self.data[pos:] if pos >= 0 else b""

    def _xref(self):
        match = re.search(rb"startxref\s+(\d+)", self.data)
        if not match:
            return None, []
        offset = int(match.group(1))
        if self.data[offset:offset + 4] != b"xref":
            return None, []
        body = self.data[offset + 4:]
        cut = body.find(b"trailer")
        if cut >= 0:
            body = body[:cut]
        lines = body.split(b"\n")
        entries = []
        cursor = 0
        while cursor < len(lines):
            head = lines[cursor].split()
            if len(head) == 2 and head[0].isdigit() and head[1].isdigit():
                start, total = int(head[0]), int(head[1])
                for step in range(total):
                    if cursor + 1 + step >= len(lines):
                        break
                    row = lines[cursor + 1 + step].split()
                    if len(row) < 3:
                        break
                    entries.append((start + step, int(row[0]), row[2]))
                cursor += 1 + total
            else:
                cursor += 1
        return offset, entries

    def _validate(self):
        problems = []
        if not self.data.startswith(b"%PDF-"):
            problems.append("missing %PDF- header")
        if not self.data.rstrip().endswith(b"%%EOF"):
            problems.append("missing %%EOF marker")
        offset, entries = self._xref()
        if offset is None:
            problems.append("no usable startxref/xref table")
        else:
            for number, position, kind in entries:
                if kind == b"f" or number == 0:
                    continue
                head = b"%d 0 obj" % number
                if self.data[position:position + len(head)] != head:
                    problems.append(
                        "xref offset for object %d does not point at it"
                        % number)
        trailer = self._trailer()
        root = _REF.search(trailer, trailer.find(b"/Root"))
        if not root:
            problems.append("trailer has no /Root reference")
        elif b"/Type /Catalog" not in self.dict_of(int(root.group(2))):
            problems.append("/Root does not resolve to a /Catalog")
        for number in sorted(self.objects):
            body, payload = self.objects[number]
            if payload is None:
                continue
            if _LENGTH.search(body):
                raw = _LENGTH.search(body).group(1)
                if not payload and int(raw) > 0:
                    problems.append("object %d stream is empty" % number)
        try:
            pages = self._collect_pages()
        except Exception as exc:  # pragma: no cover - defensive
            problems.append("page tree is unreadable: %s" % exc)
        else:
            declared = self._declared_count()
            if declared is not None and declared != len(pages):
                problems.append("/Count %d disagrees with %d page objects"
                                % (declared, len(pages)))
            if not pages:
                problems.append("document has no pages")
            for index, page in enumerate(pages, 1):
                payloads = [self.payload_of(ref) for ref in page["contents"]]
                if not payloads or not any(payloads):
                    problems.append(
                        "page %d has no decodable content stream" % index)
        return tuple(problems)

    def _declared_count(self):
        for number in sorted(self.objects):
            body = self.objects[number][0]
            if b"/Type /Pages" in body or b"/Type/Pages" in body:
                match = re.search(rb"/Count\s+(\d+)", body)
                if match:
                    return int(match.group(1))
        return None

    def _collect_fonts(self):
        fonts = {}
        for number in sorted(self.objects):
            body = self.objects[number][0]
            if b"/BaseFont" not in body:
                continue
            name = re.search(rb"/Name\s*/([^\s/\[\]()<>]+)", body)
            if not name:
                continue
            token = name.group(1).decode("latin-1")
            cmap = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
            if cmap:
                entry = self.objects.get(int(cmap.group(1)))
                codes = width = None
                if entry and entry[1] is not None:
                    codes, width = _parse_cmap(
                        decode_stream(_filter_of(entry[0]), entry[1]))
                fonts[token] = _Font(token, codes, width or 1)
            else:
                fonts[token] = _Font(token)
        return fonts

    def _collect_pages(self):
        trailer = self._trailer()
        root = _REF.search(trailer, trailer.find(b"/Root"))
        catalog = self.dict_of(int(root.group(2))) if root else b""
        pages = _REF.search(catalog, catalog.find(b"/Pages"))
        if not pages:
            return []
        collected = []
        self._walk(int(pages.group(2)), b"", collected, set())
        return collected

    def _walk(self, number, inherited, out, seen):
        if number in seen or len(out) > 512:
            return
        seen.add(number)
        body = self.dict_of(number)
        if not body:
            return
        resources = inherited
        own = body.find(b"/Resources")
        if own >= 0:
            resources = body[own:own + 400]
        if b"/Type /Page" in body and b"/Type /Pages" not in body:
            out.append({
                "number": number,
                "contents": _collect_refs(body, b"/Contents"),
                "resources": resources,
                "media_box": re.search(rb"/MediaBox\s*\[([^\]]*)\]", body),
            })
            return
        kids = re.search(rb"/Kids\s*\[([^\]]*)\]", body)
        if kids:
            for kid in re.findall(rb"(\d+)\s+\d+\s+R", kids.group(1)):
                self._walk(int(kid), resources, out, seen)

    def _text_of(self, page):
        runs = []
        for number in page["contents"]:
            runs.extend(_runs(self.payload_of(number), self._fonts))
        return runs


def _filter_of(body: bytes) -> bytes:
    match = re.search(rb"/Filter\s*(\[[^\]]*\]|/[A-Za-z0-9]+)", body)
    return match.group(1) if match else b""


def _collect_refs(body: bytes, key: bytes):
    pos = body.find(key)
    if pos < 0:
        return []
    tail = body[pos + len(key):pos + len(key) + 200]
    if tail.lstrip()[:1] == b"[":
        return [int(n) for n in re.findall(rb"(\d+)\s+\d+\s+R", tail)]
    match = re.match(rb"\s*(\d+)\s+\d+\s+R", tail)
    return [int(match.group(1))] if match else []


def _runs(stream: bytes, fonts):
    """Text runs drawn by one content stream, in emission order."""
    out = []
    font = None
    stack = [[]]
    for kind, value in tokenize(stream):
        if kind == "open":
            stack.append([])
        elif kind == "close":
            array = stack.pop() if len(stack) > 1 else []
            stack[-1].append(array)
        elif kind == "op":
            operands = stack[-1]
            if value == b"Tf" and len(operands) >= 2:
                name = operands[-2]
                if isinstance(name, bytes):
                    font = fonts.get(name.decode("latin-1"), font)
            elif value in _SHOW:
                for item in operands:
                    parts = item if isinstance(item, list) else [item]
                    for part in parts:
                        if isinstance(part, bytes):
                            out.append(font.decode(part) if font else
                                       part.decode("cp1252", "replace"))
            stack[-1] = []
        else:
            stack[-1].append(value)
    return out


def extract_text(data: bytes) -> str:
    """Every text run drawn by the document, one per line."""
    return PdfDocument(data).text


def latin_text(data: bytes) -> str:
    """Latin-bearing text runs only -- safe for content assertions."""
    return PdfDocument(data).latin_text
