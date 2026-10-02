"""Structured clinical-urgency detection (H-3).

Why this module exists
----------------------
The original detector was a flat list of regexes evaluated against the whole
turn, so every rule was unconditional: it either fired or did not. That produced
two opposite failures at the same time.

* **Recall** - only 20 of the 40 realistic emergency phrasings in the red-team
  corpus matched anything. There was no Devanagari coverage at all; breathing
  negation ("saans nahi chal rahi") was not a known synonym; an intensifier
  between an anatomical site and a symptom ("seene mein *tez* dard") broke the
  match; and vague complaints (plain pain, fever, trauma, allergy, dizziness)
  had no way to become urgent because they carried no severity of their own.
* **Precision** - the only remaining way to add recall was to add bare keywords,
  which is what escalates "accident hua tha pichle saal" or "allergy ki dawai
  leni hai" to a human handoff.

So a symptom word is never sufficient on its own. A symptom becomes urgent only
when its own context conditions hold:

1. **Severity gate** - vague symptoms need an intensifier, a complication or a
   measured value. "pet mein dard" is not urgent; "pet mein tez dard aur ulti"
   is. "Do din se bukhar hai" is not urgent; "bukhar 104 degree" is.
2. **Temporal / hypothetical scope** - a symptom inside a completed-past,
   hypothetical or third-hand clause is a story, not a presentation. An explicit
   present-tense re-arm ("ab bhi", "still", "abhi bhi") defeats suppression, so
   "chest pain tha, ab bhi hai" is still escalated.
3. **Proximity negation** - "mujhe bukhar nahi hai" is not an emergency, but
   "maine goli nahi khayi, bukhar hai" is. Negation therefore only cancels a
   symptom bound to it by position, and never for symptoms where the *absence* is
   the emergency: "saans nahi aa rahi" - no breath coming - is an emergency, so
   the breathing group is exempt.
4. **Diminisher** - "halka chakkar", "mild fever" are explicitly downgraded.

Scope is evaluated per clause (clauses split on ``, ; . ! ?`` and the Devanagari
danda), which is what stops a severity word in one sentence from upgrading an
unrelated symptom in another.

Triage questions ("kya mujhe hospital jaana chahiye") are not emergencies, but
they must still reach a human, so they are reported separately as
``triage_question`` and routed to ``medical_advice`` by the caller.

**This module changes no escalation, ordering or mutation-safety behaviour.**
It only fills in ``TurnSignals.clinical_urgent``. ``engine._safety_precheck``
still runs before identity, before any tool call, and therefore before every
book / reschedule / cancel mutation, and ``clinical_urgent`` still outranks
``medical_advice``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["detect_clinical_urgency"]

# "word" glue that tolerates Devanagari zero-width non-joiner / joiner.
_W = r"[\s\u200c\u200d]*"
# Intensity: how far a severity or negation marker may sit from a symptom.
_SEVERITY_WINDOW = 60
_NEGATION_AFTER = 25
_NEGATION_BEFORE = 12
_DIMINISHER_AFTER = 12
_DIMINISHER_BEFORE = 12


def _norm(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\u200c\u200d]", "", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    return text.strip()


# --------------------------------------------------------------------------
# context vocabulary
# --------------------------------------------------------------------------

# An explicit present-tense re-arm outranks any past/hypothetical suppression.
# Checked over the whole turn, not one clause: "chest pain tha, ab bhi hai" and
# "dard nahi tha, ab bahut tez dard ho raha hai" are both about now.
_REARM = re.compile(
    r"\b(?:ab\s*bhi|abhi\s*bhi|ab\s*hi|still|even\s+now"
    r"|ab\s*(?:\w+\s+){0,4}?ho\s*(?:raha|rahi|rah[ae]|rhu)\b"
    r"|ab\s*to|aaj\s*bhi|fir\s*se|phir\s*se|ab\s*hi\s*bhi)\b"
    r"|अभी\s*भी|अब\s*भी|अभी\s*फिर|अब\s*भी\s*भी"
)

# Completed past, or an explicitly resolved complaint.
_PAST = re.compile(
    r"\b(?:th[ai]|raha\s*tha|rahi\s*thi|hua\s*t[ha]|hui\s*t[hi]|hota\s*tha"
    r"|kehte\s*the|ho\s*chuka|ho\s*chuki|ho\s*chuke"
    r"|pichl[aeio]?\s*(?:saal|sal|mahin\w*|hafte|hapte|din|raat|week|month|year)"
    r"|last\s+(?:night|week|month|year)|yesterday|purana|purani|purane|\bold\b"
    r"|\d+\s*(?:saal|years?|months?)\s*(?:pehle|pahlay|ago|past)"
    r"|ek\s+hafte?\s+pehle|do\s*din\s*pehle"
    r"|used\s+to|recovered|over\s+now|resolved)\b"
    r"|हो\s*(?:गया|गयी|चुका|चुकी)\s*(?:था|थी)|पिछल[ेए]?"
    r"|बीते|कल\s*(?:रात|शाम)|पहले\s*(?:हुआ|था|थी)"
)

# Discourse frame: the caller is illustrating something rather than
# reporting it. These scope *forward*, so they are checked against the whole
# turn: "example ke liye bataun, bukhar 104 degree kya hai".
_HYPOTHETICAL_FRAME = re.compile(
    r"\b(?:example|suppose|maujooda|jais[ae]|jaisey|socho|samjho)\b"
    r"|\u0909\u0926\u093e\u0939\u0930\u0923|\u091c\u0948\u0938\u0947"
)

# Local hypothetical / third-hand reporting, scoped to one clause so that a
# stray "agar" cannot suppress an unrelated present-tense symptom.
_HYPOTHETICAL_LOCAL = re.compile(
    r"\b(?:agar|agar\s*to|if\b|suna\s*(?:hai|tha|thi)|kaha\s*tha|bataya\s*tha"
    r"|mana\s*lo)\b"
    r"|\u0905\u0917\u0930|\u092f\u0926\u093f"
)

# Downgrades: "halka chakkar", "mild fever", "slight pain".
_DIMINISHER = re.compile(
    r"\b(?:halka|halki|thoda|thodi|thoda\s*sa|thodi\s*si|mild|slight|slightly"
    r"|barely|minor|sa\s*hi|ekdum\s*nahi|kam\s*zor|halka\s*sa)\b"
    r"|हल्क[ाए]|थोड़[ाी]|मामूली"
)

# Complaint explicitly stated as over / resolved.
_RESOLVED_RE = re.compile(
    r"\b(?:ab\s*theek|theek\s*ho\s*g(?:aya|ayi)|sab\s*theek|recovered"
    r"|back\s+to\s+normal|ab\s*normal|clear\s+ho\s+gaya)\b"
    r"|अब\s*ठीक|ठीक\s*हो\s*(?:गया|गई)"
)

_NEGATION = re.compile(
    r"(?<![a-z])(?:nahi|nahin|nhi|nahee|nahi\s*hai|nahi\s*ho"
    r"|kabhi\s*nahi|ne\s*nahi|ko\s*nahi|se\s*nahi|bina|bina\s*ke"
    r"|no|not|never|none|nothing|without|avoid(?:ing)?"
    r"|don'?t|does\s*n[o']?t|doesn'?t|is\s*n[o']?t|isn'?t|aren'?t|wasn'?t"
    r"|नहीं|नही|नहि|बिना)\b"
)

# A connector between a marker and its symptom means the marker belongs to
# something else: "maine goli nahi khayi aur bukhar hai" keeps the fever, and
# "seene mein dard ... saans thodi phool rahi" keeps the chest pain.
_BINDING_BREAKER = re.compile(
    r"[,;]|\b(?:aur|and|lekin|but|par|ya|or|और|लेकिन|पर)\b"
)

# Severity: intensifiers, complications and destinations.
_SEVERITY = re.compile(
    r"\b(?:bahut|bohot|bhot|tez|tez\s*dard|sakht|shar|had\s*sa|severe|critical"
    r"|intense|extreme|unbearable|worst|killed\s*me|ulti|ulti\s*(?:ho|aa|ho\s*r"
    r"a|ho\s*rahi)|vomit|vomiting|retching|behosh|hosh\s*(?:gaya|gayi|kh[oa])"
    r"|unconscious|faint|kani|gir|patna|toot|fracture|hospital|ambulance"
    r"|emergency|108|chest|seene|saans|breathless|saans\s*lene"
    r"|khoon|bleed\w*|blood|dard\s*\d|wilt|poison|thand|pee\s*g\w*|stool|diarrh\w*)\b"
    r"|बहुत|तेज|सख्त|उल्टी|बेहोश|होश\s*(?:गया|गयी)|खून|सांस|कमर|दर्द|अस्पताल|एम्बुलेंस"
)

# A measured high temperature is itself severity.
_HIGH_TEMP = re.compile(
    r"(?<!\d)(?:10[3-9]|1[1-9]\d)\s*(?:\u00b0|degrees?\b|deg\b)"
    r"|(?:bukhar|fever|temperature|temp|farmaan)\W{0,8}(?<!\d)(10[3-9]|1[1-9]\d)(?!\d)"
    r"|(?:10[3-9]|1[1-9]\d)\s*(?:\u00b0|degree)?\s*(?:bukhar|ज्वर)"
    r"|(?:bukhar|ज्वर|बुखार)\s*(?:10[3-9]|1[1-9]\d)"
)

# Not an emergency, but the caller is asking whether it is - must reach a human.
_TRIAGE_QUESTION = re.compile(
    r"(?:kya|kyunki)\s*(?:mujhe|main|hum)\s*(?:hospital|emergency|doctor|clinic"
    r"|ambulance|emergency\s*ward|aasmani)\s*(?:jaana|jaun|chahiye|jau|bhej|bulau)"
    r"|(?:kya|should|shall)\s*(?:i|main|mujhe)\s*(?:go|call|come|visit|see)\b"
    r"|should\s+i\s+(?:go|call|come|visit)"
    r"|hospital\s*(?:jaana|jana|jau|jaun|chahiye|padhna)\s*(?:chahiye|ya)"
    r"|kya\s*(?:ye\s*)?(?:emergency|medical)\s*(?:hai|kya)"
    r"|is\s+it\s+an?\s*emergency"
    r"|(?:kya|should)\s*(?:main|i|mujhe)\s*(?:ambulance|emergency)\s*"
    r"|(?:ambulance|helpline)\s*(?:bulaun|bula\s*sakoon|chahiye)"
    r"|क्या\s*(?:मुझे|मुंझे)\s*(?:अस्पताल|एम्बुलेंस|इमरजेंसी)\s*(?:जाना|जाऊँ|चाहिए|बुलाऊँ)"
)


def _clause_span(text: str, index: int) -> tuple[int, int]:
    """Boundaries of the clause containing ``index``."""
    start = 0
    end = len(text)
    for i in range(index - 1, -1, -1):
        if text[i] in ",;.!?\n\u0964\u0965\u0966":
            start = i + 1
            break
    for i in range(index, len(text)):
        if text[i] in ",;.!?\n\u0964\u0965\u0966":
            end = i
            break
    return start, end


def _bound(text: str, start: int, end: int, pattern: re.Pattern[str],
           after: int, before: int) -> bool:
    """True when a marker matches one bound to *this* occurrence of a symptom.

    Binding is positional on purpose. Both markers are contextual operators that
    qualify the symptom they sit next to, and both can appear in a sentence that
    contains a *different* symptom further along - which must not be touched:

        "Waise abhi seene mein dard ho raha hai aur saans thodi phool rahi hai."
            -> 'thodi' must not downgrade the chest pain
        "maine goli nahi khayi aur bukhar hai"
            -> 'nahi' must not cancel the fever
    """
    for m in pattern.finditer(text):
        if end <= m.start() <= end + after:
            if not _BINDING_BREAKER.search(text[end:m.start()]):
                return True
        elif m.end() <= start <= m.end() + before:
            if not _BINDING_BREAKER.search(text[m.end():start]):
                return True
    return False


def _negated(text: str, start: int, end: int) -> bool:
    """True when a negation is bound to *this* occurrence of a symptom."""
    return _bound(text, start, end, _NEGATION, _NEGATION_AFTER, _NEGATION_BEFORE)


def _diminished(text: str, start: int, end: int) -> bool:
    """True when a diminisher ("halka", "mild", "thoda sa") binds to this symptom."""
    return _bound(text, start, end, _DIMINISHER, _DIMINISHER_AFTER, _DIMINISHER_BEFORE)


def _severe(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - _SEVERITY_WINDOW):end + _SEVERITY_WINDOW]
    return bool(_SEVERITY.search(window) or _HIGH_TEMP.search(window))


# --------------------------------------------------------------------------
# symptom groups
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Symptom:
    key: str
    pattern: re.Pattern[str]
    #: vague complaint - only urgent with a severity marker
    needs_severity: bool = False
    #: the *absence* of this symptom is itself the emergency
    negation_is_symptom: bool = False


_SYMPTOMS: tuple[_Symptom, ...] = (
    # -- breathing, part 1: Hindi/Urdu constructions where the negation IS the
    #    symptom ("no breath coming"). Exempt from proximity negation.
    _Symptom("breathing_distress", re.compile(
        r"(?:saans|sans|shwas|shaan)\s*(?:thodi|thoda|bhad|halki|halka|hi|to|kaafi|fully"
        r"|poori|tamam)?\s*(?:phool|phuul|phol|chadh|chhalang|chalti"
        r"|nahi|nahin|nhi|na\s*hi|ruki|ruk\s*rahi|band|bandi|nahi\s*(?:aa|chal))"
        r"|(?:saans|sans)\s*(?:lene|chalne)\s*(?:mein|me|nahi|nahin|nhi|ko\s*nahi)"
        r"|(?<![\w])(?:nahi|nahin|nhi)\s+(?:saans|sans)\s*(?:aa|chal|phool|le)"
        r"|साँस|सांस|सवस|श्वास"
        r"(?:\s*\S{0,6}){0,3}?\s*(?:नहीं|नही|न चल|नहीं चल|बंद|नहीं आ|नहीं ले)"
    ), negation_is_symptom=True),
    # -- breathing, part 2: symptom nouns, where "no breathlessness" denies
    #    the symptom and must suppress it like any other negated symptom.
    _Symptom("breathing_symptom_word", re.compile(
        r"breathless|dyspn[oe]ea|gasping|choking|choke\s*on"
        r"|(?:cannot|can\s*not|can['\u2019]?t|unable\s+to)\s+breathe"
        r"|shortness\s+of\s+breath|breathing\s+difficulty|difficulty\s+breathing"
        r"|lungs?\s+(?:are\s+)?fail"
        r"|\bno\s+breath\b"
    )),
    # -- conscious level / imminent collapse: always urgent on its own.
    _Symptom("loss_of_consciousness", re.compile(
        r"\bbehosh\b|\bhosh\s*(?:gaya|gayi|kh[oa])\b|\bunconscious\b|\bcoma\b"
        r"|\bpassed\s+out\b|\bblacked?\s*out\b"
        r"|\bfaint(?:ed|ing|s)?\b|\bcollaps(?:e|ed|ing)\b"
        r"|(?<![\w])बेहोश|होश\s*(?:गया|गयी|उड़)|बेहोशी"
    )),
    # -- named clinical events: unambiguous, no severity needed.
    _Symptom("cardiac_or_stroke_event", re.compile(
        r"heart\s*attack|heart\s*stroke|cardiac\s*arrest|\bstroke\b"
        r"|one\s+side\s+(?:of\s+(?:my|his|her)\s+body\s+)?(?:is\s+)?(?:weak|weakness|paralysed|paralyzed|numb)"
        r"|(?:face|cheek|mouth)\s+(?:is\s+)?(?:droop|drooping|drooped|slapped)"
        r"|slurred\s+speech|cannot\s+speak|can'?t\s+speak"
        r"|हार्ट\s*अटैक|दिल\s*का?\s*(?:दौरा|रुक)|स्ट्रोक|लकवा|गिरा\s*पटक|अटैक"
    )),
    # -- chest pain: an intensifier may sit between the site and the symptom.
    _Symptom("chest_pain", re.compile(
        r"(?:seene|chati|sine|chest|dil|heart)\s*(?:mein|me|main|me\s*mein|ko)?\s*"
        r"(?:bahut|bohot|bhot|tez|sakht|shar)?\s*dard"
        r"|(?:seene|chati|dil)\s*(?:mein|me|main)?\s*(?:jal\s*raha|jal\s*rha|dard|heavy)"
        r"|(?:dil|heart)\s*(?:bahut|bohot)?\s*dhadak"
        r"|chest\s*(?:pain|aches|aching|hurts|hurting|tight|pressure)"
        r"|pain\s+(?:in|on)\s+(?:my\s+)?(?:chest|left\s+side)"
        r"|(?:angina|heartburn)\s+attack"
        r"|सीने|सीन|दिल|चीती|छाती"
        r"\s*\S{0,4}\s*दर्द"
    )),
    # -- any active bleeding is urgent.
    _Symptom("bleeding", re.compile(
        r"khoon\s*(?:aa\s*ra|aa\s*rha|aa\s*raha|aa\s*rahi|beh|baha|bah\s*raha|bah\s*rahi|nikal\w*)"
        r"|(?:naak|kan|nose|khoon)\s*(?:se)?\s*khoon"
        r"|\bbleeding\b|\bblood\s+(?:is\s+)?(?:coming|flowing|coughing|pouring)"
        r"|\bblood\s+in\s+(?:my\s+)?(?:vomit|stool|urine|sputum)"
        r"|(from\s+)?(?:nose|mouth|ear|eye)\s+(?:is\s+)?bleeding"
        r"|\bh(?:a)?eemorrhage\b|\bhemorrhage\b"
        r"|खून\s*(?:बह|निकल|आ)"
    )),
    # -- vague: needs an intensifier.
    _Symptom("severe_pain", re.compile(
        r"(?:bahut|bohot|bhot|had\s*sa|sakht|shar|severe|critical|extreme"
        r"|unbearable|worst)\s*(?:tez\s*)?(?:dard|pain|दर्द)"
        r"|tez\s*(?:tez\s*)?dard"
        r"|(?:extreme|severe)\s+(?:pain|aching)"
        r"|दर्द\s*(?:बहुत|तेज|ज़्यादा)"
    )),
    # -- vague abdominal complaint: needs an intensifier or complication.
    _Symptom("abdominal_acute", re.compile(
        r"(?:pet|pait|paet|tummy|abdomen\w*|stomach|belly|lower\s*ab"
        r"|kamra)\s*(?:mein|me|main|ko)?\s*(?:bahut|bohot|tez|sakht|shar)?\s*"
        r"(?:dard|pain|jal)"
        r"|(?:severe|bad|terrible|cramping)\s+(?:abdominal|stomach|belly|tummy)\s*pain"
        r"|(?:pet|pait|paet)\s*mein\s*(?:bahut|tez)\s*(?:dard|जोड़|मरोड़)"
        r"|पेट|पेट\s*में|तोड़|कमर\s*में"
        r"\s*\S{0,4}\s*(?:दर्द|पीड़ा)"
    ), needs_severity=True),
    # -- vague fever: needs an intensifier or a measured high value.
    _Symptom("high_fever", re.compile(
        r"\b(?:bukhar|fever|temperature|temp|feverish|farmaan)\b"
        r"|ज्वर|बुखार|तापमान"
    ), needs_severity=True),
    # -- a present-tense accident; past/hypothetical is filtered by scope.
    _Symptom("trauma", re.compile(
        r"\baccident\b(?!\s*(?:insurance|report|claim|cover|coverage|policy"
        r"|ka\s+report|ki\s+report|the\s+ki|ka\b|ki\b))"
        r"|\bhadsa\b|\bhadse\b|\bhadse\b|\btrauma\b|\bcrash\b"
        r"|(?:gadbad|took\s+an\s+accident|car\s+accident|bike\s+accident)"
        r"|(?:gir\s*(?:gaya|hua)|gire\s*hai|h\s*daste|h\s*gire|h\s*phata"
        r"|marr\s*gaya|mar\s*gaya)"
        r"|सड़क\s*से|हादसा|हादसे|दुर्घटना|गिर\s*(?:गया|गई)"
    )),
    # -- vague: an explicit diminisher ("thoda sa chakkar") downgrades it.
    _Symptom("dizziness", re.compile(
        r"\bchakkar\b|\bdizzy\b|\bvertigo\b|\bspin(?:ning)\s+head\b"
        r"|\bhead\s*(?:is\s+)?(?:spinning|revolving)\b"
        r"|\bna\stumme\b|\bkaam\s*orbit\b"
        r"|चक्कर|घूम\s*रहा"
    )),
    # -- a reaction, not the word "allergy": "allergy ki dawai leni hai" is not
    #    an emergency.
    _Symptom("severe_allergic_reaction", re.compile(
        r"allergic\s+reaction|anaphyla\w*|\b(?:skin\s+pe|cheek|cheeks|face|aankh|ankh"
        r"|throat|kanthi|gale|gala|hont|thele|labial)\s*(?:mein|pe|ko)?\s*"
        r"(?:phool|laal|suja|sujan|swelling|rickh|bad\s*gaya)"
        r"|(?:sujan|suja|phool|rickh|\u0938\u0942\u091c\u0928|\u092f\u0932)\s*"
        r"(?:ho\s*rha|ho\s*rahi|hai|ho\s*gai)?\s*(?:mer[ei]?\s*)?"
        r"(?:gale|gala|kanthi|throat|\u0917\u0932\u0947|\u0915\u0902\u0925\u0940)"
        r"|(?:gale|gala|kanthi|hont|thele|throat)\s*"
        r"(?:mein|me|ko|pe)?\s*(?:phool|sujan|suja|rickh|swelling)"
        r"|(?:\u0917\u0932\u0947|\u0917\u0932\u093e|\u0915\u0902\u0925\u0940|\u0939\u094b\u0902\u0920|\u091c\u0940\u092d|\u0917\u093e\u0932|\u091f\u0902\u0915)\s*"
        r"(?:\u092e\u0947\u0902|\u092e\u0947|\u0915\u093e|\u0915\u0940|\u0915\u094b)?\s*"
        r"(?:\u0938\u0942\u091c\u0928|\u0938\u0942\u091c|\u092b\u0942\u0932\u0940|\u0916\u0941\u091c\u0932\u0940)"
        r"|\bhives\b|\bru[sh]?\s*ya\s*nikal|\bface\s+(?:has\s+)?swelled\b"
        r"|allergy\s+ho\s*(?:gaya|gayi|rahi|ho\s*gayi|gayi\s*hai|ho\s*rha)"
        r"|(?:dawai|medicine|goli|insulin)\s*(?:se)?\s*allergy"
        r"|(?:dawai|medicine)\s*(?:lene|khane)\s*(?:se)?\s*(?:baad\s*)?"
        r"(?:kharab|allergy|chhap)"
        r"|एलर्जी\s*(?:हो\s*(?:गई|गया|हुई|हुए)|का\s*प्रभाव)|सुजन|खुजली"
    )),
    # -- explicit statement of impending death.
    _Symptom("impending_collapse", re.compile(
        r"jaan\s*(?:mazaa|maza|chali|chalo|nikal\w*|par\s*ja\w*)|mar\s*(?:ja\w*|raha\s*hai)"
        r"|\bdying\b|\bgoing\s+to\s+die\b|\bwill\s+die\b|\bmight\s+die\b"
        r"|जान\s*(?:मज़ा|मजा|चल\w*)|मर\s*(?:जा\w*|रहा)"
    )),
)


def detect_clinical_urgency(turn: str) -> tuple[bool, bool]:
    """Return ``(clinical_urgent, triage_question)`` for one caller turn.

    ``triage_question`` means "is this an emergency?" - not an emergency, but
    the caller still needs a human, so the caller routes it to ``medical_advice``.
    """
    text = _norm(turn)
    if not text:
        return False, False

    framed = bool(_HYPOTHETICAL_FRAME.search(text))
    # An explicit present-tense re-arm anywhere outranks past or hypothetical
    # scope: "chest pain tha, ab bhi hai" is about now. Turn-wide, so hoisted.
    rearmed = bool(_REARM.search(text))

    for symptom in _SYMPTOMS:
        for m in symptom.pattern.finditer(text):
            start, end = m.span()
            if not rearmed:
                cstart, cend = _clause_span(text, start)
                clause = text[cstart:cend]
                if (
                    framed
                    or _PAST.search(clause)
                    or _RESOLVED_RE.search(clause)
                    or _HYPOTHETICAL_LOCAL.search(clause)
                ):
                    continue
            if symptom.needs_severity and not _severe(text, start, end):
                continue
            if not symptom.negation_is_symptom and _negated(text, start, end):
                continue
            if _diminished(text, start, end):
                continue
            return True, False

    return False, bool(_TRIAGE_QUESTION.search(text))