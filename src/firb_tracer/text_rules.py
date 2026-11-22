"""The basic reader: fixed sentence patterns, no outside service.

It reads an ownership summary in Chinese or English, one statement at a
time, and recognises these forms (percentages may use % or "per cent"):

Sentences
    A 持有 B 25% 股权            A holds 25% of B / A owns a 25% stake in B
    A 持有 25% 的 B 股权          B is 25% owned by A
    B 由 A 持股 25%               B is a wholly owned subsidiary of A
    A 全资持有 B / B 是 A 的全资子公司
    A 拟收购 B 25% 股权           A proposes to acquire 25% of B   (marked proposed)

Shareholder lists, where a heading names the company held
    B 的股东：A 25%，C 75%        Shareholders of B: A 25%; C 75%
    B 股东如下：                  (then one shareholder per line, e.g. "A 25%" or "25% A")

Defined terms
    深圳资源集团有限公司（以下简称"深圳资源"）   Alpha Pty Ltd (the "Buyer")
    Later uses of the short name are read as the full name. A defined term
    "Buyer"/"买方" or "Target"/"目标公司" also sets the buyer or target, as do
    lines such as "Buyer: A" or "目标公司为 B".

What it does not read: a percentage with no holder ("25% C公司" outside a
shareholder list), indirect percentages ("A 通过 B 间接持有 C 10%"), voting
arrangements, vetoes, board seats and anything else. Statements that look
like they are about ownership or control but match no pattern are listed as
unread, so the user can enter them by hand or use the model reader.
"""

from __future__ import annotations

import re
import unicodedata

from .extraction import Extraction, Found

NUM = r"(?P<pct>\d+(?:\.\d+)?)"
SHARE_WORDS = r"(?:股权|股份|权益|股票|出资份额|出资|份额|表决权)"
ZH_HOLD = r"(?:直接)?(?:持有|拥有|持股|收购|受让|认购|购买|取得|增持|入股)"
EN_HOLD = (r"(?:directly\s+)?(?:holds?|owns?|has|acquires?|buys?|purchases?|subscribes?\s+for|takes?|"
           r"acquire|buy|purchase|hold|own)")
EN_STAKE = r"(?:stake|interest|equity\s+interest|shareholding|of\s+the\s+(?:issued\s+)?(?:shares|equity))"

PROPOSED = re.compile(
    r"拟|计划|准备|将要|将|"
    r"\b(?:proposes?|plans?|intends?|has\s+agreed|agreed|agrees|is)\s+to\b|\bproposed\b|\bwill\b",
    re.I,
)

# Patterns that give holder A, held B and a percentage. Tried in order; the
# first whose names pass the sanity check wins.
SENTENCE_PATTERNS: list[re.Pattern] = [
    # wholly owned: no percentage in the text, 100% implied
    re.compile(r"^(?P<A>.+?)全资(?:持有|拥有|控股)(?P<B>.+?)$"),
    re.compile(r"^(?P<B>.+?)(?:是|为|系)(?P<A>.+?)(?:的)?全资子公司$"),
    re.compile(r"^(?P<B>.+?)由(?P<A>.+?)全资(?:持有|拥有|控股)$"),
    re.compile(r"^(?P<B>.+?)\s+is\s+(?:a\s+)?wholly[- ]owned(?:\s+subsidiary)?\s+(?:of|by)\s+(?P<A>.+?)$", re.I),
    re.compile(r"^(?P<A>.+?)\s+wholly\s+owns\s+(?P<B>.+?)$", re.I),
    # passive forms
    re.compile(rf"^(?P<B>.+?)由(?P<A>.+?){ZH_HOLD}{NUM}%.*$"),
    re.compile(rf"^(?P<B>.+?)\s+is\s+{NUM}\s*%\s*(?:owned|held)\s+by\s+(?P<A>.+?)$", re.I),
    # active forms
    re.compile(rf"^(?P<A>.+?){ZH_HOLD}(?P<B>.+?){NUM}\s*%\s*(?:的)?{SHARE_WORDS}?$"),
    re.compile(rf"^(?P<A>.+?){ZH_HOLD}{NUM}\s*%\s*(?:的)?(?P<B>.+?)(?:的)?{SHARE_WORDS}?$"),
    re.compile(rf"^(?P<A>.+?)\s+{EN_HOLD}\s+(?:an?\s+|the\s+)?{NUM}\s*%\s*{EN_STAKE}?\s*(?:of|in)\s+(?P<B>.+?)$",
               re.I),
]

ZH_LIST_HEADER = re.compile(
    r"^(?P<B>.+?)(?:的)?(?:股东|股权结构|出资人|持股情况)(?:情况|结构|及持股比例|及出资比例)?"
    r"(?:如下|为|包括|是)?\s*:\s*(?P<rest>.*)$"
)
ZH_LIST_HEADER_NO_COLON = re.compile(r"^(?P<B>.+?)的股东(?:为|包括|是)(?P<rest>.+)$")
EN_LIST_HEADERS = [
    re.compile(r"^(?:the\s+)?(?:shareholders?|owners?|equity\s+holders?)\s+(?:of|in)\s+(?P<B>.+?)"
               r"\s*(?:are|is|include|comprise)?\s*:\s*(?P<rest>.*)$", re.I),
    re.compile(r"^(?P<B>.+?)(?:'s)?\s+(?:shareholders?|ownership)\s*(?:are|is|include)?\s*:\s*(?P<rest>.*)$", re.I),
]
LIST_ITEMS = [
    re.compile(rf"^(?P<A>.+?)\s*\(?\s*(?:持股|持有|出资|holds?|owns?|holding)?\s*(?:比例)?\s*:?\s*{NUM}\s*%"
               rf"\s*(?:的)?(?:{SHARE_WORDS}|{EN_STAKE})?\s*\)?$", re.I),
    re.compile(rf"^{NUM}\s*%\s*(?:由)?\s*(?P<A>.+?)$"),
]

BUYER_WORDS = {"buyer", "acquirer", "purchaser", "investor", "买方", "收购方", "投资方", "受让方"}
TARGET_WORDS = {"target", "target company", "目标公司", "标的公司", "收购标的", "标的"}
ROLE_LINE = re.compile(
    r"^(?:the\s+)?(?P<role>buyer|acquirer|purchaser|target(?:\s+company)?|买方|收购方|目标公司|标的公司|收购标的)"
    r"\s*(?:is|为|是|系|:)\s*(?P<name>.+)$",
    re.I,
)
DEFINED_TERM = re.compile(
    r"\(\s*(?:以下简称|以下称|下称|简称|hereinafter(?:\s+referred\s+to\s+as)?|together)?\s*:?\s*"
    r"(?:the\s+)?[\"“「'‘](?P<alias>[^\"”」'’)]{1,40})[\"”」'’]\s*\)",
    re.I,
)
DEFINED_TERM_LOOSE = re.compile(r"\(\s*(?:以下简称|以下称|下称|简称)\s*:?\s*(?P<alias>[^)]{1,40})\)")
BEFORE_TERM = re.compile(r"[^,;:。、\n]{1,80}$")
# Trims "A 持有 " / "A owns 100% of " from in front of a defined name. Bare "of"
# and "in" are not cut, because they occur inside names (Bank of China).
LEADING_VERB = re.compile(
    r"^.*(?:持有|拥有|收购|受让|认购|为|是|由|\bholds?\b|\bowns?\b|\bacquires?\b|\bis\b|\bby\b|"
    r"%\s*(?:stake|interest)?\s*(?:of|in)\b)\s*",
    re.I,
)

RELEVANT = re.compile(
    r"%|持有|持股|股东|收购|控股|控制|表决|否决|董事|委派|一致行动|代持|间接|"
    r"\bholds?\b|\bowns?\b|\bowned\b|shareholder|acquir|subsidiar|control|voting|veto|board|director|nominee|"
    r"indirect",
    re.I,
)
CONNECTORS = re.compile(r"^(?:并且|并|而|同时|另外|此外|其中|且|以及|and|also|while|whereas|further(?:more)?)\s*",
                        re.I)
BULLET = re.compile(r"^\s*(?:[-*•·▪◦]|\d+[.)、]|\(\d+\)|[一二三四五六七八九十]+、)\s*")
DATE = re.compile(r"(?:于|在)?\d{4}年(?:\d{1,2}月)?(?:\d{1,2}日)?|\b(?:in|on)\s+\d{4}\b", re.I)
BAD_NAME = re.compile(r"%|持有|持股|收购|由|\bholds?\b|\bowns?\b|\bacquire|\bowned\b")
MODIFIERS = re.compile(r"另外|额外|\b(?:a\s+)?further\b|\ban?\s+additional\b|\banother\b", re.I)
# Indirect percentages are computed figures, not holdings: reading one as an
# edge would double count it, so these are always left unread.
INDIRECT = re.compile(r"间接|穿透|\bindirect(?:ly)?\b|\bthrough\b|\bvia\b", re.I)
SENTENCE_END = re.compile(
    r"(?<!\bCo)(?<!\bPty)(?<!\bNo)(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bSt)(?<!\be\.g)"
    r"\.\s+(?=[A-Z\"“(])"
)


# --------------------------------------------------------------------------
# Text preparation
# --------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Full-width punctuation to ASCII, 'per cent' to %, and no commas inside company names."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s*(?:per\s*cent|percent)\b", "%", text, flags=re.I)
    text = re.sub(r",\s*(?=(?:Ltd|Limited|Inc|LLC|L\.P\.|LP|Pty|plc|Co)\b)", " ", text, flags=re.I)
    return text


def _key(name: str) -> str:
    return re.sub(r"^the\s+", "", name.strip(), flags=re.I).casefold()


def _clean(name: str) -> str:
    name = DATE.sub("", name)
    name = re.sub(r"^[\s\"“”「」'‘’,:.]+|[\s\"“”「」'‘’,:.]+$", "", name)
    name = re.sub(r"(?:的)?(?:股权|股份)$", "", name)
    name = re.sub(r"的$", "", name)
    return name.strip()


def _valid(name: str) -> bool:
    return bool(name) and len(name) <= 80 and not BAD_NAME.search(name) and not re.fullmatch(r"[\d.\s]+", name)


class _Reader:
    def __init__(self, text: str) -> None:
        self.text = _normalise(text)
        self.out = Extraction(reader="rules")
        self.aliases: dict[str, str] = {}
        self.last_held: str | None = None

    # -- defined terms -----------------------------------------------------

    def collect_defined_terms(self) -> None:
        for pattern in (DEFINED_TERM, DEFINED_TERM_LOOSE):
            for m in pattern.finditer(self.text):
                before = BEFORE_TERM.search(self.text[: m.start()])
                if not before:
                    continue
                full = _clean(LEADING_VERB.sub("", before.group(0)))
                alias = _clean(m.group("alias"))
                if not _valid(full) or not alias:
                    continue
                self.aliases[_key(alias)] = full
                if _key(alias) in BUYER_WORDS:
                    self.out.buyer = full
                if _key(alias) in TARGET_WORDS:
                    self.out.target = full
            self.text = pattern.sub("", self.text)

    def resolve(self, name: str) -> str:
        return self.aliases.get(_key(name), name)

    # -- recording ---------------------------------------------------------

    def record(self, holder: str, held: str, pct: float, proposed: bool, source: str) -> bool:
        holder, held = self.resolve(_clean(holder)), self.resolve(_clean(held))
        if not (_valid(holder) and _valid(held)) or holder == held or not 0 < pct <= 100:
            return False
        source = re.sub(r"\.{2,}", ".", re.sub(r"\s+([.,;:])", r"\1", source)).strip()
        self.out.add(Found(holder=holder, held=held, pct=pct, proposed=proposed, source=source))
        self.last_held = held
        return True

    # -- one statement -----------------------------------------------------

    def sentence(self, clause: str, original: str) -> bool:
        role = ROLE_LINE.match(clause)
        if role:
            name = self.resolve(_clean(role.group("name")))
            if _valid(name):
                if _key(role.group("role")).startswith(("target", "目标", "标的", "收购标的")):
                    self.out.target = name
                else:
                    self.out.buyer = name
                return True

        rel = re.match(r"^(?:which|that)\s+(.*)$", clause, re.I)
        if rel and self.last_held:
            clause = f"{self.last_held} {rel.group(1)}"
        rel = re.match(r"^(?:其|该公司|后者)(.*)$", clause)
        if rel and self.last_held:
            clause = f"{self.last_held}{rel.group(1)}"

        if INDIRECT.search(clause):
            return False
        proposed = bool(PROPOSED.search(clause))
        plain = PROPOSED.sub(" ", clause) if proposed else clause
        plain = MODIFIERS.sub(" ", plain)
        # The seller is not part of the holding: "... from Li Si", "从李四处受让 ..."
        plain = re.sub(r"\s+from\s+[^,;]+$", "", plain, flags=re.I)
        plain = re.sub(r"(?:从|向)[^从向]+?(?:处)?(?=收购|受让|购买|认购)", "", plain)
        plain = re.sub(r"\s+", " ", plain).strip()

        for pattern in SENTENCE_PATTERNS:
            m = pattern.match(plain)
            if not m:
                continue
            pct = float(m.group("pct")) if "pct" in m.groupdict() and m.group("pct") else 100.0
            if self.record(m.group("A"), m.group("B"), pct, proposed, original):
                return True
        return False

    @staticmethod
    def looks_like_sentence(line: str) -> bool:
        plain = MODIFIERS.sub(" ", PROPOSED.sub(" ", line))
        return bool(INDIRECT.search(line)) or any(p.match(plain.strip()) for p in SENTENCE_PATTERNS)

    def list_item(self, parent: str, item: str, original: str) -> bool:
        for pattern in LIST_ITEMS:
            m = pattern.match(item.strip())
            if m and self.record(m.group("A"), parent, float(m.group("pct")), False, original):
                return True
        return False

    def list_header(self, line: str) -> tuple[str, str] | None:
        for pattern in (ZH_LIST_HEADER, ZH_LIST_HEADER_NO_COLON, *EN_LIST_HEADERS):
            m = pattern.match(line)
            if m:
                parent = self.resolve(_clean(m.group("B")))
                if _valid(parent):
                    return parent, m.group("rest")
        return None

    # -- the whole text ----------------------------------------------------

    def run(self) -> Extraction:
        self.collect_defined_terms()
        parent: str | None = None
        for raw_line in self.text.splitlines():
            line = BULLET.sub("", raw_line).strip()
            if not line:
                parent = None
                continue

            header = self.list_header(line)
            if header:
                parent, rest = header
                for item in re.split(r"[,;、。]", rest):
                    if item.strip() and not self.list_item(parent, item, f"{parent}: {item.strip()}"):
                        self.unread(item)
                continue

            if parent:
                items = [i for i in re.split(r"[,;、。]", line) if i.strip()]
                if items and not self.looks_like_sentence(line) and all(
                    any(p.match(i.strip()) for p in LIST_ITEMS) for i in items
                ):
                    for item in items:
                        if not self.list_item(parent, item, f"{parent}: {item.strip()}"):
                            self.unread(item)
                    continue
                parent = None

            for clause in re.split(r"[。;]|,(?!\d)", SENTENCE_END.sub("。", line)):
                clause = CONNECTORS.sub("", clause.strip()).strip()
                if clause and not self.sentence(clause, clause):
                    self.unread(clause)

        if self.out.buyer is None:
            buyers = {h.holder for h in self.out.holdings if h.proposed}
            if len(buyers) == 1:
                self.out.buyer = buyers.pop()
        return self.out

    def unread(self, clause: str) -> None:
        clause = clause.strip()
        if clause and RELEVANT.search(clause) and clause not in self.out.unread:
            self.out.unread.append(clause)


def read_text(text: str) -> Extraction:
    """Read an ownership summary with the fixed patterns above."""
    return _Reader(text).run()
