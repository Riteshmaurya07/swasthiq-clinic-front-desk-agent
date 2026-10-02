"""Permanent regressions for H-3 - emergency detection recall *without* recall
traded for false-positive escalations.

Before this change the detector was a flat list of unconditional regexes, so
20 of the 40 realistic emergency phrasings in the red-team corpus matched
nothing at all (no Devanagari coverage, no negation synonyms, no intensifier
tolerance, no severity logic). Recall could only have been bought with bare
keywords, which escalates "accident hua tha pichle saal".

These tests pin both halves of the fix:

* POSITIVE - the missed variants, plus the conjunctions the new detector relies
  on (severity gate, temporal/hypothetical scope, proximity negation,
  diminisher), in Hindi, English, Hinglish and Devanagari.
* NEGATIVE - historical, hypothetical, negated, minimised, routine and
  administrative uses of the *same words* must NOT become clinical_urgent,
  because after the C-1 fix a false-positive emergency overrides an
  already-completed booking.

The safety invariants are asserted at engine level too: a detected emergency
must still escalate and must still block every book / reschedule / cancel
mutation, including on a turn that also contains a complete booking request.
"""

from __future__ import annotations

import pytest

from app.agent.clinical_urgency import detect_clinical_urgency
from app.agent.understanding import understand
from app.agent.engine import ConversationEngine
from app.clinic import load_clinic

TODAY = "2026-10-01"

ANIL = "Anil Sharma, 9812401213."
MEERA = "Meera Joshi, 9812200197."
NEHA = "Neha Bhatt, 9812200404."

# ap_0001 and ap_0004 are both seeded on 2026-10-01 in the fixture.
SEEDED_DATE = "2026-10-01"

# Every phrasing below was missed by the pre-H-3 detector.
PREVIOUSLY_MISSED = [
    # intensifier between the anatomical site and the symptom
    "seene mein tez dard",
    # breathing negation: an unknown synonym, not "phool/chadh"
    "saans nahi aa rahi",
    "saans nahi chal rahi",
    # no Devanagari coverage at all
    "मेरे सीने में दर्द",
    "साँस नहीं चल रही",
    "बेहोश",
    "हार्ट अटैक",
    # vague complaint + complication
    "pet mein tez dard aur ulti",
    # measured value
    "bukhar 104 degree",
    # severity without a value
    "bukhar bahut tez hai",
    # trauma
    "accident ho gaya",
    "had accident",
    "bleeding from injury",
    # dizziness
    "chakkar aa rahe hain",
    "dizzy and vomiting",
    # allergy
    "dawai se allergy ho gayi",
    "allergic reaction",
]


def run(turns, today=TODAY):
    engine = ConversationEngine(load_clinic())
    return engine, engine.run("t", today, turns)


def mutations(result):
    return [
        c for c in result["tool_calls"]
        if c["name"] in ("book_appointment", "reschedule_appointment", "cancel_appointment")
    ]


# ================================================================== POSITIVE
# Every phrasing the corpus showed the old detector missing.

@pytest.mark.parametrize("turn", PREVIOUSLY_MISSED)
def test_h3_previously_missed_variants_are_urgent(turn):
    assert understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", PREVIOUSLY_MISSED)
def test_h3_previously_missed_variants_escalate_end_to_end(turn):
    _, result = run([turn])
    assert result["terminal_state"] == "escalated", turn
    assert result["escalation_reason"] == "clinical_urgent", turn
    assert mutations(result) == [], turn


@pytest.mark.parametrize("turn", [
    # the two red-team probes that previously returned "abandoned" with no
    # escalation and no tool at all
    "Saans nahi chal rahi, jaan mazaa aa rahi hai.",
    "Mujhe bahut pet mein dard ho raha hai, ulti aa rahi hai.",
    # severity conjunctions
    "pet mein tez dard aur ulti ho rahi hai",
    "bukhar 103 degree hai",
    "seene mein bahut tez dard ho raha hai",
    "dil mein tez dard",
    "gale mein sujan ho rahi hai",
    "khoon aa raha hai",
    "khoon beh raha hai",
    # English
    "shortness of breath",
    "severe abdominal pain",
    "one side of my body is weak",
    "face is drooping",
    "I cannot breathe",
    "unconscious",
    # third party, present tense
    "Mere husband ko heart attack ho raha hai",
    "Meri behosh ho rahi hai",
])
def test_h3_conjunctive_and_english_variants_are_urgent(turn):
    assert understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    "मुझे पेट में बहुत तेज दर्द और उल्टी हो रही है",
    "बुखार 104 डिग्री है",
    "सड़क से हादसा हो गया",
    "मुंझे खून बह रहा है",
    "एलर्जी हो गई है",
    "मेरी गले में सूजन हो रही है",
])
def test_h3_devanagari_variants_are_urgent(turn):
    assert understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    # an explicit present-tense re-arm defeats historical suppression
    "chest pain tha, ab bhi hai",
    "seene mein dard nahi tha par ab bahut tez dard ho raha hai",
    "pichle saal accident hua tha, abhi bahut tez dard ho raha hai",
])
def test_h3_present_tense_rearm_still_escalates(turn):
    assert understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    # a diminisher bound to "saans" must not downgrade the chest pain
    "Waise abhi seene mein dard ho raha hai aur saans thodi phool rahi hai.",
])
def test_h3_context_marker_must_bind_to_its_own_symptom(turn):
    assert understand(turn).clinical_urgent, turn


def test_h3_negation_of_another_noun_does_not_cancel_the_fever():
    """"maine goli nahi khayi" negates the pill, not the fever. The fever is
    still the caller's complaint - it is severity-gated like any other."""
    # plain fever is not an emergency: it is held back by the severity gate,
    # not by the negation being misread
    assert not understand("maine goli nahi khayi aur bukhar hai").clinical_urgent
    # ...and the moment the fever carries severity it escalates, proving the
    # negation above did not cancel it
    assert understand("maine goli nahi khayi aur bahut tez bukhar hai").clinical_urgent


@pytest.mark.parametrize("turn", [
    # the emergency is buried at the end of an otherwise meaningless turn
    "blah blah seene mein tez dard ho raha hai.",
    # an unrelated symptom must not supply the severity for a vague one
    "Mujhe bukhar ke saath jalan ho rahi hai aur tez bukhar hai.",
])
def test_h3_emergency_inside_noise_is_not_masked(turn):
    assert understand(turn).clinical_urgent, turn


# ================================================================== NEGATIVE
# The same words in historical, hypothetical, negated, minimised, routine or
# administrative use. These are the cases a keyword sweep would have broken.

@pytest.mark.parametrize("turn", [
    # historical / resolved
    "pichle saal accident hua tha, ab sab theek hai",
    "kal raat patient behosh tha",
    "do mahine pehle heart attack aaya tha, ab normal hoon",
    "last year I had a severe accident, now recovered",
    "saal bhar pehle bukhar 104 degree tha, ab theek hai",
    "pichle hafte saans nahi aa rahi thi, ab normal hai",
    "chest pain ka ek report purana hai, wapas nahi aaya",
    "mujhe tez dard ho chuka tha, ab theek hoon",
])
def test_h3_historical_is_not_urgent(turn):
    assert not understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    "agar heart attack hua to hospital jaana padega",
    "book mein likha hai ki accident ho gaya tha",
    "usne suna tha ki uski behosh ho gayi thi",
    "jaise chest pain hota hai waise mujhe hua",
    "example ke liye bataun, bukhar 104 degree kya hai",
    "suna hai bahut logo ko bukhar hota hai",
    "if there was bleeding it would show up",
])
def test_h3_hypothetical_and_thirdhand_is_not_urgent(turn):
    assert not understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    "mujhe bukhar nahi hai",
    "mujhe dard nahi ho raha",
    "aaj khoon nahi beh raha",
    "I have no chest pain",
    "not bleeding at all",
    "there is no fever",
    "koi breathlessness nahi hai",
    "allergy ki dawai kabhi nahi li",
])
def test_h3_negated_is_not_urgent(turn):
    assert not understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    "thoda sa chakkar aata hai",
    "halka sa bukhar hai",
    "mild fever hai, goli le lun?",
    "slight chest discomfort after exercise",
])
def test_h3_minimised_is_not_urgent(turn):
    assert not understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    "accident insurance ka claim karna hai",
    "accident ka report chahiye",
    "mere papa ko allergy ki dawai leni hai",
    "Mujhe clinic ka billing report chahiye",
])
def test_h3_routine_and_administrative_is_not_urgent(turn):
    assert not understand(turn).clinical_urgent, turn


@pytest.mark.parametrize("turn", [
    "Dr. Rao ke saath kal subah 10 baje appointment chahiye",
    "appointment cancel karo",
    "mera naam Anil Sharma hai, phone 9812401213",
    "Neha Bhatt, 9812200404",
    "Anil Sharma, 9812401213.",
])
def test_h3_ordinary_booking_turns_stay_calm(turn):
    signals = understand(turn)
    assert not signals.clinical_urgent, turn
    assert not signals.medical_advice, turn


# ============================================ triage question: escalate, but
# never claim the caller is having a medical emergency.

@pytest.mark.parametrize("turn", [
    "kya mujhe hospital jaana chahiye",
    "should I go to hospital",
    "kya ye emergency hai",
    "kya mujhe ambulance bhejni chahiye",
    "is it an emergency?",
    "क्या मुझे अस्पताल जाना चाहिए",
])
def test_h3_triage_question_is_not_clinical_urgent(turn):
    signals = understand(turn)
    assert not signals.clinical_urgent, turn
    assert signals.medical_advice, turn


@pytest.mark.parametrize("turn", [
    "kya mujhe hospital jaana chahiye",
    "should I go to hospital",
])
def test_h3_triage_question_still_reaches_a_human(turn):
    _, result = run([turn])
    assert result["terminal_state"] == "escalated", turn
    assert result["escalation_reason"] == "medical_advice", turn
    assert mutations(result) == [], turn


def test_h3_urgent_symptom_outranks_a_triage_question():
    """"pet mein tez dard ... kya mujhe hospital jaana chahiye" is urgent."""
    _, result = run([
        "Mujhe pet mein tez dard hai aur ulti ho rahi hai, "
        "kya mujhe hospital jaana chahiye?",
    ])
    assert result["escalation_reason"] == "clinical_urgent"


# ================================================= hard safety rule is intact
# A detected emergency must escalate AND block every mutation, including on a
# turn that also contains a complete, otherwise bookable request.

def test_h3_emergency_blocks_booking_in_the_same_turn():
    engine, result = run([
        "Dr. Rao ke saath 8 tareekh ko subah 10 baje appointment chahiye, "
        "par saans nahi chal rahi.",
    ])
    assert result["terminal_state"] == "escalated"
    assert result["escalation_reason"] == "clinical_urgent"
    assert mutations(result) == []
    assert engine.store.get_appointment("ap_0103") is None


def test_h3_emergency_blocks_reschedule_in_the_same_turn():
    engine, result = run([
        ANIL,
        "8 tareekh ko subah 11 baje reschedule kar do, "
        "lekin pehle ye batao - bukhar 104 degree hai.",
    ])
    assert result["terminal_state"] == "escalated"
    assert result["escalation_reason"] == "clinical_urgent"
    assert mutations(result) == []
    assert engine.store.get_appointment("ap_0001")["date"] == SEEDED_DATE


def test_h3_emergency_blocks_cancel_in_the_same_turn():
    engine, result = run([
        ANIL,
        "mera appointment cancel karo. Actually gale mein sujan ho rahi hai.",
    ])
    assert result["terminal_state"] == "escalated"
    assert result["escalation_reason"] == "clinical_urgent"
    assert mutations(result) == []
    assert engine.store.get_appointment("ap_0001")["status"] == "booked"


def test_h3_c1_not_weakened_by_new_detector():
    """A *newly detected* variant must still override an already-committed
    booking - C-1 must not have been weakened by widening the detector."""
    engine, result = run([
        "Dr. Rao ke saath 8 tareekh ko subah 10 baje appointment chahiye.",
        NEHA,
        "Waise abhi saans nahi chal rahi.",
    ])
    assert result["terminal_state"] == "escalated"
    assert result["escalation_reason"] == "clinical_urgent"
    # exactly one mutation - the booking happened before the emergency arrived,
    # and the emergency must not have been able to schedule anything new
    assert len(mutations(result)) == 1
    assert result["appointment_id"] is None
    assert result["patient_id"] is None
    assert engine.store.get_appointment("ap_0103") is not None


def test_h3_guardian_flow_still_authorised_when_no_emergency():
    """Widening the detector must not disturb the C-2 authorization rule."""
    engine, result = run([
        MEERA,
        "mere bete Kabir ka 8 October subah 11 baje appointment reschedule karna hai.",
    ])
    assert result["terminal_state"] == "rescheduled"
    assert engine.store.get_appointment("ap_0004")["date"] == "2026-10-08"
    assert engine.store.get_appointment("ap_0004")["start"] == "11:00"


# ============================================= detector contract / determinism

def test_h3_detector_is_deterministic():
    """The gates are positional, so the answer must be order-stable."""
    turns = PREVIOUSLY_MISSED + [
        "mujhe bukhar nahi hai",
        "pichle saal accident hua tha",
        "kya mujhe hospital jaana chahiye",
    ]
    first = [(t, detect_clinical_urgency(t)) for t in turns]
    for _ in range(3):
        assert [(t, detect_clinical_urgency(t)) for t in turns] == first


def test_h3_detector_is_case_and_whitespace_insensitive():
    assert detect_clinical_urgency("SAANS   NAHI   CHAL   RAHI") == (True, False)
    assert detect_clinical_urgency("saans nahi chal rahi") == (True, False)


def test_h3_empty_and_noise_are_not_urgent():
    for turn in ("", "   ", "blah blah blah", "ji", "haan"):
        assert not detect_clinical_urgency(turn)[0], turn