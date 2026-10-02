"""Deterministic turn understanding for the conversation engine.

Reads one caller turn and returns structured signals (intent, identity,
doctor, date, time, third-party target). Rule-based only: no LLM, no
sampling — which is what makes the safety behaviour testable.

Language coverage follows the supplied conversations: English, Hindi
(Hinglish) and the mix; relative dates ("aaj", "kal", "parso"), weekday
words, "N tareekh", Hindi clock times ("gyarah baje", "subah 10 baje"),
part of day ("subah", "shaam"), mid-sentence corrections (the LAST
mention of a date-ish signal in the turn wins), and third-party targets
("Kabir ko dikhana hai", "mere bete Aarav ke liye", "Lakshmi Iyer ka
appointment cancel karna hai").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.agent.clinical_urgency import detect_clinical_urgency

WEEKDAYS = {
    "somwar": 0, "monday": 0, "mon": 0,
    "mangalwar": 1, "tuesday": 1, "tue": 1, "tues": 1,
    "budhwar": 2, "wednesday": 2, "wed": 2,
    "guruwar": 3, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "shukrawar": 4, "friday": 4, "fri": 4,
    "shanivaar": 5, "shaniwar": 5, "saturday": 5, "sat": 5,
    "itwaar": 6, "sunday": 6, "sun": 6,
}

HINDI_NUMBERS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "panch": 5,
    "chah": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "bara": 12, "barah": 12, "terah": 13, "tera": 13,
    "chaudah": 14, "pandrah": 15, "solah": 16,
}

ENGLISH_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
}

DATE_IN_TURNS = {"aaj": 0, "today": 0, "kal": 1, "tomorrow": 1, "parso": 2}

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

INJECTION_MARKERS = [
    "ignore your previous instructions",
    "ignore all previous instructions",
    "ignore previous instructions",
    "disregard your instructions",
    "administrator mode",
    "admin mode",
    "developer mode",
    "authorised internal test",
    "authorized internal test",
    "system prompt",
    "you are now in",
    "act as the",
    "enter maintenance mode",
    "override your rules",
    "cancel every appointment",
    "cancel all appointments",
    "cancel everything",
    "bulk cancel",
    "bulk-cancel",
    "you are authorized now",
    "you are authorised now",
    "ignore patient authorization",
    "ignore patient authorisation",
]

ADVICE_PATTERNS = [
    r"goli\s*le\s*lun",
    r"(?:aur|another|one\s*more)\s+(?:ek\s+)?goli",
    r"kitni\s*der\s*mein?\s*(?:utar|khatam)",
    r"kitna\s*(?:mg|milligram)",
    r"\bdose\b|\bdosage\b",
    r"kya\s*(?:main|mai)\s*(?:le|kha)\w*\s*(?:lun|ya)",
    r"le\s*lun\s*ya\s*nahi",
    r"kha\s*lun\s*ya\s*nahi",
    r"kaunsi\s*(?:dawai|goli|medicine)",
    r"kitni\s*der\s*mein\s*utar",
    r"kya\s*(?:bimari|problem)\s*hai",
    r"kya\s*sahi\s*ilaj",
    # H-3: the remaining realistic phrasings from the signal matrix.
    r"ye\s*goli\s*lun\s*ya\s*nahi",
    r"ye\s*dawai\s*le\s*lun",
    r"\w+\s*ki\s*dawai\s*leni\s*chahiye",
    r"mujhe\s*kya\s*khaana\s*chahiye",
    r"side\s*effects?\s*kya\s*(?:hain|hai)",
    r"injection\s*(?:lagwa|laga)\s*lena\s*chahiye",
]

NAME_STRIP_LEADING = {"bas", "just", "mera", "meri", "yeh", "ye", "hm", "umm"}
NAME_STRIP_TRAILING = {"ji"}

# Words that open turns but are never names.
GREETING_WORDS = {
    "namaste", "namaskar", "hello", "hi", "accha", "acha", "arre", "theek",
    "haan", "han", "ok", "okay", "ji", "haanji", "helloji",
}


@dataclass
class TurnSignals:
    raw: str
    injection: bool = False
    clinical_urgent: bool = False
    medical_advice: bool = False
    intent: str | None = None
    patient_name: str | None = None
    phone: str | None = None
    target_name: str | None = None
    doctor_name: str | None = None
    weekday: str | None = None          # canonical Mon..Sun
    relative_date: str | None = None    # aaj|kal|parso
    day_number: int | None = None
    month_number: int | None = None
    time: str | None = None             # HH:MM 24h
    part_of_day: str | None = None      # morning|afternoon|evening
    accept_any_time: bool = False
    caller_disengaged: bool = False
    mentions_dependent: bool = False  # 'mere bete...' with no name yet


def _extract_phone(text: str) -> str | None:
    # First as-is; then allowing spaces between digit groups ("98122 00011").
    m = re.search(r"\b(9\d{9})\b", text)
    if m:
        return m.group(1)
    squeezed = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
    m = re.search(r"\b(9\d{9})\b", squeezed)
    return m.group(1) if m else None


def _extract_intent(text: str) -> str | None:
    if re.search(r"\bcancel\b", text):
        return "cancel"
    if re.search(
        r"reschedule|\bbadalna\b|\bshift\b|\bchange\s+karna|"
        r"use\s+\w+\s+karwana|usko\s+\w+\s+karwana|\bkarwana\s+hai\s*.{0,12}\buse\b",
        text,
    ):
        return "reschedule"
    if re.search(
        r"appointment\s*(?:chahiye|karwana|book|chahiye\s+tha|hai\b)|milna\s*hai|"
        r"dikhana\s*hai|book\s*karna|lagwana|aa\s*sak(?:ta|te)|kal\s*ho\s*jayega",
        text,
    ):
        return "book"
    return None


def _extract_doctor(text: str) -> str | None:
    m = re.search(r"\bdr\.?\s*([a-z]+)", text)
    return m.group(1) if m else None


def _pos(pattern: str, text: str):
    m = re.search(pattern, text)
    return (m.start(), m) if m else None


def _last_date_signal(text: str):
    """Date resolution with caller corrections in mind.

    The LAST date-ish mention in the turn wins, regardless of kind — a caller
    correcting themselves speaks their final choice last ("Mangalwar 6
    tareekh... nahi nahi, budhwar, 7 tareekh" → day 7; "9 tareekh... nahi
    nahi, 10 tareekh Shanivaar" → day 10, and its weekday corroborates it).
    Ties (same position) prefer the more specific kind: day > relative > weekday.
    Returns (weekday | None, relative | None, day | None, month | None).
    """
    last_weekday = last_relative = None
    last_day = last_month = None
    last_day_pos = last_rel_pos = last_wd_pos = -1

    for token, wd in WEEKDAYS.items():
        hit = _pos(rf"\b{token}\b", text)
        if hit and hit[0] > last_wd_pos:
            last_wd_pos = hit[0]
            last_weekday = wd

    for token, offset in DATE_IN_TURNS.items():
        hit = _pos(rf"\b{token}\b", text)
        if hit and hit[0] > last_rel_pos:
            last_rel_pos = hit[0]
            last_relative = offset

    # "3 tareekh" / "7 October" — a bare number followed by a clock word
    # ("9 baje") is NOT a date, so the suffix is required.
    for m in re.finditer(r"\b(\d{1,2})\s*(?:tareekh|tarikh)\b", text):
        if 1 <= int(m.group(1)) <= 31:
            last_day, last_month, last_day_pos = int(m.group(1)), None, m.start()
    for m in re.finditer(rf"\b(\d{{1,2}})\s+({'|'.join(MONTH_NAMES)})\b", text):
        if 1 <= int(m.group(1)) <= 31:
            last_day, last_month, last_day_pos = int(m.group(1)), MONTH_NAMES[m.group(2)], m.start()

    # Day-number is the most specific signal and wins when it does not
    # contradict a co-occurring weekday/relative word; a contradiction means
    # the caller corrected themselves, so the LATER mention wins.
    def _wd_conflicts_with_day(candidate_wd: int) -> bool:
        from datetime import datetime as _dt
        try:
            if last_month is not None:
                probe = _dt(2026 if True else 2026, last_month, last_day)
            else:
                probe = None  # month unknown: cannot check consistency
        except ValueError:
            return False
        if probe is None:
            return False
        return probe.weekday() != candidate_wd

    if last_day is not None:
        if last_weekday is not None and last_month is not None and _wd_conflicts_with_day(last_weekday):
            # explicit contradiction: later mention wins
            if last_wd_pos > last_day_pos:
                return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][last_weekday], None, None, None
        return None, None, last_day, last_month
    if last_relative is not None and last_wd_pos <= last_rel_pos:
        # a relative word later than (or absent) a weekday mention wins;
        # 'aaj ka appointment ... use Saturday karwana' -> Saturday wins
        return None, {0: "aaj", 1: "kal", 2: "parso"}[last_relative], None, None
    if last_weekday is not None:
        return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][last_weekday], None, None, None
    return None, None, None, None


def _extract_time(text: str):
    """Return (HH:MM | None, part_of_day | None) from Hindi/English phrasing."""
    m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        minute = m.group(2)
        if m.group(3) == "pm" and hour < 12:
            hour += 12
        return f"{hour:02d}:{minute}", None

    number_words = "|".join(list(HINDI_NUMBERS) + list(ENGLISH_NUMBERS))
    m = re.search(
        r"\b(subah|savere|morning|dopahar|afternoon|shaam|evening|raat)?\s*"
        rf"(\d{{1,2}}|{number_words})\s*baje",
        text,
    )
    if m:
        part = m.group(1)
        token = m.group(2)
        hour = HINDI_NUMBERS.get(token, ENGLISH_NUMBERS.get(token))
        if hour is None:
            hour = int(token)
        if 0 <= hour <= 23:
            pod = None
            if part in ("subah", "savere", "morning"):
                pod = "morning"
            elif part in ("dopahar", "afternoon"):
                pod = "afternoon"
            elif part in ("shaam", "evening", "raat"):
                pod = "evening"
            else:
                pod = "morning" if hour < 12 else ("afternoon" if hour < 16 else "evening")
            return f"{hour:02d}:00", pod

    if re.search(r"\b(subah|savere|morning)\b", text):
        return None, "morning"
    if re.search(r"\b(dopahar|afternoon)\b", text):
        return None, "afternoon"
    if re.search(r"\b(shaam|evening|raat)\b", text):
        return None, "evening"
    return None, None


def _clean_name(candidate: str) -> str | None:
    candidate = candidate.strip().rstrip(".")
    words = [w for w in candidate.split() if w.lower() not in NAME_STRIP_LEADING]
    while words and words[-1].lower() in NAME_STRIP_TRAILING:
        words.pop()
    if not words:
        return None
    # Reject greetings and doctor titles: "Dr. Rao ke saath..." must not
    # produce a caller named 'Dr'.
    if all(w.lower() in GREETING_WORDS or w.lower() in {"dr", "doctor"} for w in words):
        return None
    return " ".join(words)


def _extract_name(text: str) -> str | None:
    # "Main <...> <Name>" — relationship words before the name
    # ("Main unki wife Kavita Rawat", "Main unka padosi hoon, Mohit Negi")
    m = re.search(
        r"\b(?i:main|mein|hum|i am|this is)\s+(?:mera|meri|mere|unki|unke|uska|uski|iska|us|un)?\s*"
        r"(?:[a-z]+\s+){0,2}?(wife|pati|bihen|behen|bhai|beta|beti|padosi|dost|saala|"
        r"mama|chacha|mausi|bua|nana|nani|relative|neighbour|neighbor|friend)\w*\s*"
        r"(?:hoon|hun|hu|here)?,?\s*((?:[A-Z][a-z]+\.?|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+\.?|[A-Z]\.)){0,2})",
        text,
    )
    if m:
        cleaned = _clean_name(m.group(2))
        if cleaned:
            return cleaned
    # "Main <Name>..." / "this is <Name>" — prefix matched case-insensitively,
    # the captured name must be capitalised words.
    m = re.search(r"\b(?i:main|mein|hum|i am|this is)\s+((?:[A-Z][a-z]+\.?|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+\.?|[A-Z]\.)){0,2})", text)
    if m:
        cleaned = _clean_name(m.group(1))
        if cleaned and cleaned.split()[0].lower() not in GREETING_WORDS:
            return cleaned
    # "<Name> bol rahi/raha hoon"
    m = re.search(r"((?:[A-Z][a-z]+\.?|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+\.?|[A-Z]\.)){0,2})\s+bol\s*rah", text)
    if m:
        cleaned = _clean_name(m.group(1))
        if cleaned and cleaned.split()[0].lower() not in GREETING_WORDS:
            return cleaned
    # "<Name>, <phone>" at turn start (greetings rejected)
    m = re.search(r"^\s*((?:[A-Z][a-z]+\.?|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+\.?|[A-Z]\.)){0,2})\s*,", text)
    if m:
        cleaned = _clean_name(m.group(1))
        if cleaned and cleaned.split()[0].lower() not in GREETING_WORDS:
            return cleaned
    # "<Name>." at turn start  ("Bas Sharma.")
    m = re.search(r"^\s*((?:[A-Z][a-z]+\.?|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+\.?|[A-Z]\.)){0,2})\s*\.", text)
    if m:
        cleaned = _clean_name(m.group(1))
        if cleaned and cleaned.split()[0].lower() not in GREETING_WORDS:
            return cleaned
    # "Main Rajesh hi hoon..." / "Rajesh hi hoon main" — self-identification
    # by bare name with the emphasis particle 'hi'
    m = re.search(r"\b([A-Z][a-z]+)\s+hi\s+(?:hoon|hun|hu)\b", text)
    if m and m.group(1).lower() not in GREETING_WORDS:
        return m.group(1)
    # ", <Name>." / ", <Name>$"  ("Main unka padosi hoon, Mohit Negi.")
    m = re.search(r",\s*((?:[A-Z][a-z]+\.?|[A-Z]\.)(?:\s+(?:[A-Z][a-z]+\.?|[A-Z]\.)){0,2})\s*(?:\.|$)", text)
    if m:
        cleaned = _clean_name(m.group(1))
        if cleaned and cleaned.split()[0].lower() not in GREETING_WORDS:
            return cleaned
    return None


def _extract_target(text: str) -> str | None:
    """Third-party patient mentions (never the caller).

    The LAST mention in the turn wins: callers correct themselves
    ("Arjun ka appointment... nahi nahi, Aarav ka appointment").
    """
    hits: list[tuple[int, str]] = []
    # "Kabir ko dikhana hai" / "<X> ko dikhana"
    for m in re.finditer(r"([A-Z][a-z]+\.?(?:\s+[A-Z][a-z]+\.?)?)\s+ko\s+(?:dikhana|milna)", text):
        hits.append((m.start(), m.group(1)))
    # "mere bete Aarav ke liye" / "beti <X> ke liye"
    for m in re.finditer(r"(?:bete|beta|beti|son|daughter)\s+([A-Z][a-z]+)", text):
        hits.append((m.start(), m.group(1)))
    # "<X> (ji) ka [aaj ka] appointment ..." (possessive third person)
    for m in re.finditer(
        r"([A-Z][a-z]+\.?(?:\s+[A-Z][a-z]+\.?)?)(?:\s+ji)?\s+ka\s+(?:aaj|kal|parso)?\s*(?:ka\s+)?appointment",
        text,
    ):
        hits.append((m.start(), m.group(1)))
    # "<X> (ji) ke liye" ("Sharma ji ke liye")
    for m in re.finditer(r"([A-Z][a-z]+)(?:\s+ji)?\s+ke\s+liye", text):
        hits.append((m.start(), m.group(1)))
    if not hits:
        return None
    hits.sort(key=lambda h: h[0])
    return hits[-1][1]


def _disengaged(text: str) -> bool:
    stripped = re.sub(r"\[[^\]]*\]", "", text)  # [background noise]
    filler = re.fullmatch(
        r"[\W]*(?:haan|theek\s*hai|hello|ji|arre|accha|ok|bas\s*yahi\s*poochna\s*tha)?[\W]*",
        stripped.lower().strip(),
    )
    return bool(filler) and not re.search(r"\d", stripped)


def understand(turn: str) -> TurnSignals:
    signals = TurnSignals(raw=turn)
    lowered = turn.lower()

    signals.injection = any(m in lowered for m in INJECTION_MARKERS)

    # H-3: urgency is conjunctive and context-aware (see clinical_urgency).
    # A triage question ("kya mujhe hospital jaana chahiye") is not an emergency
    # but must still reach a human, so it escalates as medical_advice.
    urgent, triage = detect_clinical_urgency(turn)
    signals.clinical_urgent = urgent
    signals.medical_advice = not urgent and (
        triage or any(re.search(p, lowered) for p in ADVICE_PATTERNS)
    )

    signals.intent = _extract_intent(lowered)
    signals.doctor_name = _extract_doctor(lowered)
    signals.phone = _extract_phone(turn)
    signals.target_name = _extract_target(turn)
    signals.patient_name = _extract_name(turn)

    wd, rel, day, month = _last_date_signal(lowered)
    signals.weekday = wd
    signals.relative_date = rel
    signals.day_number = day
    signals.month_number = month

    signals.time, signals.part_of_day = _extract_time(lowered)

    # A bare doctor+date+time specification is a booking request even when
    # the caller skips verbs ("8 tareekh subah 9 baje Dr. Rao ke saath.").
    if signals.intent is None and signals.doctor_name and (
        signals.day_number is not None or signals.weekday or signals.relative_date
    ) and (signals.time or signals.part_of_day):
        signals.intent = "book"

    if re.search(r"koi\s*bhi\s*time\s*chalega|any\s*time|jo\s*mil\s*jaye", lowered):
        signals.accept_any_time = True
    # A dependent is mentioned without a name yet ('mere bete ke liye...'):
    # the action concerns someone other than the caller.
    if signals.target_name is None and re.search(
        r"\b(?:mere|meri|mera)\s+(?:bete|beta|beti|son|daughter)\b", lowered
    ):
        signals.mentions_dependent = True
    signals.caller_disengaged = _disengaged(lowered)
    return signals
