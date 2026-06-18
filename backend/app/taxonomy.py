"""
Haryana grievance taxonomy — the controlled vocabulary that makes AI routing
auditable and consistent.

Every AI recommendation is constrained to THIS vocabulary (categories,
departments, routing offices), so two similar complaints can never be routed
to two different departments by chance — a problem the CM-office brief calls
out explicitly ("Similar complaints may be categorized differently by
different officers").

Maintained by the department in production (a config file, not code).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Departments and their service categories, Citizen-Charter SLA (in days),
# and the routing office level. SLA values are illustrative defaults that the
# department finalises; the engine treats them as data, not logic.
# ---------------------------------------------------------------------------

DEPARTMENTS: dict[str, dict] = {
    "Power / Bijli (UHBVN-DHBVN)": {
        "categories": [
            "Power Outage / Supply Failure",
            "Faulty / Sparking Transformer",
            "Billing Dispute",
            "New Connection / Meter",
            "Voltage Fluctuation",
            "Loose / Dangling Wires (Safety)",
        ],
        "sla_days": 7,
        "routing": "Sub-Divisional Officer (Operations), DISCOM",
    },
    "Public Health Engineering (Water & Sewerage)": {
        "categories": [
            "No Water Supply",
            "Contaminated / Dirty Water",
            "Pipeline Leakage / Burst",
            "Sewerage Overflow / Blockage",
            "Tubewell / Handpump Failure",
        ],
        "sla_days": 7,
        "routing": "Junior Engineer (PHED), Sub-Division",
    },
    "Public Works (Roads & Buildings)": {
        "categories": [
            "Potholes / Damaged Road",
            "Broken / Missing Streetlight",
            "Blocked / Damaged Drain",
            "Unsafe Public Building",
        ],
        "sla_days": 15,
        "routing": "Junior Engineer (PWD B&R)",
    },
    "Revenue & Disaster Management": {
        "categories": [
            "Land Records / Jamabandi Correction",
            "Patwari / Tehsil Service Delay",
            "Mutation (Intkaal) Pending",
            "Compensation / Relief",
            "Encroachment on Public Land",
        ],
        "sla_days": 30,
        "routing": "Tehsildar / Naib-Tehsildar",
    },
    "Police / Home": {
        "categories": [
            "Law & Order / Safety Threat",
            "Women Safety / Harassment",
            "FIR Not Registered",
            "Cyber / Online Fraud",
            "Traffic / Public Nuisance",
        ],
        "sla_days": 3,
        "routing": "SHO, concerned Police Station",
    },
    "Health & Family Welfare": {
        "categories": [
            "Medicine / Equipment Shortage",
            "Staff Absenteeism",
            "Ambulance / Emergency Service",
            "Hospital Negligence",
        ],
        "sla_days": 7,
        "routing": "Senior Medical Officer (CHC/PHC)",
    },
    "Education": {
        "categories": [
            "Teacher Shortage / Absence",
            "School Infrastructure",
            "Scholarship / Fee Issue",
            "Mid-Day Meal",
        ],
        "sla_days": 15,
        "routing": "Block Education Officer",
    },
    "Urban Local Bodies / Municipal": {
        "categories": [
            "Garbage / Sanitation",
            "Stray Animals",
            "Illegal Construction",
            "Property Tax / Birth-Death Certificate",
        ],
        "sla_days": 15,
        "routing": "Sanitary Inspector / Municipal Engineer",
    },
    "Social Justice & Empowerment": {
        "categories": [
            "Old-Age / Widow / Disability Pension",
            "BPL / Ration Card",
            "Scheme Benefit Not Received",
        ],
        "sla_days": 30,
        "routing": "District Social Welfare Officer",
    },
    "Food, Civil Supplies & Consumer Affairs": {
        "categories": [
            "Ration / PDS Shop Issue",
            "Overcharging / Black-marketing",
            "LPG / Kerosene",
        ],
        "sla_days": 15,
        "routing": "Inspector, Food & Supplies",
    },
}

# Flat list of all valid categories (for the structured-output enum / validation)
ALL_CATEGORIES: list[str] = [
    c for d in DEPARTMENTS.values() for c in d["categories"]
]
ALL_DEPARTMENTS: list[str] = list(DEPARTMENTS.keys())

# Haryana districts (routing destination geography)
DISTRICTS: list[str] = [
    "Ambala", "Bhiwani", "Charkhi Dadri", "Faridabad", "Fatehabad",
    "Gurugram", "Hisar", "Jhajjar", "Jind", "Kaithal", "Karnal",
    "Kurukshetra", "Mahendragarh", "Nuh", "Palwal", "Panchkula",
    "Panipat", "Rewari", "Rohtak", "Sirsa", "Sonipat", "Yamunanagar",
]


def department_for_category(category: str) -> str | None:
    for dept, meta in DEPARTMENTS.items():
        if category in meta["categories"]:
            return dept
    return None


def sla_for_category(category: str) -> int:
    dept = department_for_category(category)
    return DEPARTMENTS.get(dept, {}).get("sla_days", 15) if dept else 15


def routing_for_category(category: str) -> str:
    dept = department_for_category(category)
    return DEPARTMENTS.get(dept, {}).get("routing", "District Grievance Cell") if dept else "District Grievance Cell"


# ---------------------------------------------------------------------------
# Safety-critical / high-urgency signal lexicon (Hindi + English + Hinglish).
# These drive the deterministic, AUDITABLE urgency floor — independent of the
# LLM — so a "sparking transformer" or "gas leak" can never be silently
# down-prioritised. This is the "department-validated rules" the brief asks for.
# ---------------------------------------------------------------------------

SAFETY_CRITICAL_SIGNALS: list[str] = [
    # English
    "spark", "sparking", "fire", "electrocut", "shock", "live wire",
    "gas leak", "collapse", "collapsed", "drowning", "accident", "blast",
    "explosion", "contaminat", "poison", "outbreak", "epidemic", "dengue",
    "snake", "molest", "rape", "assault", "kidnap", "missing child",
    "suicide", "threat to life", "bleeding", "unconscious",
    # Hindi (Devanagari)
    "चिंगारी", "आग", "करंट", "बिजली का झटका", "गैस रिसाव", "गिर गया",
    "हादसा", "दुर्घटना", "धमाका", "जहर", "जहरीला", "महामारी", "डेंगू",
    "सांप", "छेड़छाड़", "बलात्कार", "अपहरण", "खतरा", "जान को खतरा",
    # Hinglish / transliterated
    "chingari", "aag", "current", "jhatka", "gas leak", "gir gaya",
    "hadsa", "durghatna", "dhamaka", "zeher", "zehrila", "mahamari",
    "saanp", "chhedchhaad", "khatra", "jaan ka khatra",
]

# Vulnerability signals (procedural priority, not necessarily safety)
VULNERABILITY_SIGNALS: list[str] = [
    "pregnant", "गर्भवती", "old age", "बुजुर्ग", "elderly", "disabled",
    "divyang", "दिव्यांग", "widow", "विधवा", "bpl", "बीपीएल",
    "child", "बच्चा", "newborn", "नवजात", "no water for", "days without",
]


# ---------------------------------------------------------------------------
# Domain gazetteer: abbreviation expansion + Hinglish→English normalisation.
# Directly targets the brief's "abbreviations, spelling variation, noisy
# administrative text" requirement. Applied BEFORE the model sees the text,
# and surfaced in reason codes so officers see what was expanded.
# ---------------------------------------------------------------------------

ABBREVIATION_GAZETTEER: dict[str, str] = {
    # Administrative offices / roles
    "cmo": "Chief Minister Office",
    "dc": "Deputy Commissioner",
    "sdm": "Sub-Divisional Magistrate",
    "bdo": "Block Development Officer",
    "sho": "Station House Officer",
    "je": "Junior Engineer",
    "xen": "Executive Engineer",
    "sdo": "Sub-Divisional Officer",
    "mc": "Municipal Committee",
    "gp": "Gram Panchayat",
    # Schemes / categories
    "bpl": "Below Poverty Line",
    "pds": "Public Distribution System (ration)",
    "fir": "First Information Report",
    "rti": "Right to Information",
    " kyc ": " Know Your Customer ",
    # Departments / utilities (Haryana-specific)
    "uhbvn": "Uttar Haryana Bijli Vitran Nigam (power)",
    "dhbvn": "Dakshin Haryana Bijli Vitran Nigam (power)",
    "phed": "Public Health Engineering Department (water)",
    "pwd": "Public Works Department (roads)",
    "hsvp": "Haryana Shahari Vikas Pradhikaran",
    "huda": "Haryana Urban Development Authority",
}

# Hinglish / transliterated common nouns → canonical English term.
HINGLISH_GAZETTEER: dict[str, str] = {
    "bijli": "electricity / power",
    "paani": "water",
    "pani": "water",
    "sadak": "road",
    "naali": "drain",
    "nali": "drain",
    "transformer": "transformer",
    "tx": "transformer",
    "patwari": "patwari (land-record officer)",
    "tehsil": "tehsil office",
    "intkaal": "mutation (land transfer)",
    "jamabandi": "land record (jamabandi)",
    "pension": "pension",
    "ration": "ration / PDS",
    "safai": "sanitation / cleaning",
    "kachra": "garbage",
    "awara pashu": "stray animals",
    "street light": "streetlight",
    "meter": "electricity meter",
    "bill": "bill",
}
