"""Synthetic, deidentified Haryana grievance dataset for the demo.

Representative of the brief's "indicative datasets": complaint text in Hindi /
English / Hinglish, category & routing history, districts, status logs.
Deliberately seeded with:
  * clusters (same issue, same locality) → demonstrates systemic-issue detection
  * safety-critical cases → demonstrates the urgency floor
  * noisy / abbreviated / transliterated text → demonstrates robustness

No real citizen data. Generated for prototype demonstration only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .taxonomy import SAFETY_CRITICAL_SIGNALS


def _d(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# id, text, district, category, department, urgency, status, summary, days_ago
_RAW = [
    # --- Water cluster: Hisar, Sector 9 (systemic) ---
    ("JS-1001", "Sector 9 Hisar mein 5 din se paani nahi aa raha, poora mohalla pareshan hai.", "Hisar", "No Water Supply", "Public Health Engineering (Water & Sewerage)", "High", "Open", "No water supply for 5 days in Sector 9, Hisar.", 4),
    ("JS-1002", "सेक्टर 9 हिसार में पीने के पानी की सप्लाई बंद है, टैंकर भी नहीं आ रहा।", "Hisar", "No Water Supply", "Public Health Engineering (Water & Sewerage)", "High", "Open", "Drinking water supply stopped in Sector 9 Hisar; no tankers.", 3),
    ("JS-1003", "No water in our street sector 9 hisar since last week, PHED not responding", "Hisar", "No Water Supply", "Public Health Engineering (Water & Sewerage)", "High", "In Progress", "Week-long water outage in Sector 9 Hisar; PHED unresponsive.", 6),
    ("JS-1004", "Sector 9 hisar paani ki problem bohot din se hai please solve karo", "Hisar", "No Water Supply", "Public Health Engineering (Water & Sewerage)", "Medium", "Open", "Persistent water problem in Sector 9 Hisar.", 2),

    # --- Transformer sparking cluster: Rohtak (safety-critical) ---
    ("JS-1010", "Transformer near our house in Rohtak is sparking badly, may catch fire anytime, very dangerous", "Rohtak", "Faulty / Sparking Transformer", "Power / Bijli (UHBVN-DHBVN)", "Critical", "Open", "Sparking transformer posing fire risk in Rohtak.", 1),
    ("JS-1011", "रोहतक में ट्रांसफार्मर से चिंगारी निकल रही है, बच्चे पास में खेलते हैं, जल्दी ठीक करवाएं।", "Rohtak", "Faulty / Sparking Transformer", "Power / Bijli (UHBVN-DHBVN)", "Critical", "Open", "Sparking transformer near children's play area, Rohtak.", 1),
    ("JS-1012", "tx spark kar raha hai model town rohtak, current ka khatra hai", "Rohtak", "Faulty / Sparking Transformer", "Power / Bijli (UHBVN-DHBVN)", "Critical", "Resolved", "Sparking transformer in Model Town, Rohtak (resolved).", 9),

    # --- Pension delays (multiple districts) ---
    ("JS-1020", "Vridha pension 3 mahine se nahi aayi, main 72 saal ka hoon, bank ja ja ke thak gaya", "Bhiwani", "Old-Age / Widow / Disability Pension", "Social Justice & Empowerment", "High", "Open", "Old-age pension pending 3 months for a 72-year-old.", 5),
    ("JS-1021", "विधवा पेंशन नहीं मिल रही, फॉर्म जमा किए 2 महीने हो गए।", "Jind", "Old-Age / Widow / Disability Pension", "Social Justice & Empowerment", "Medium", "Open", "Widow pension not received 2 months after applying.", 7),
    ("JS-1022", "Disability pension band ho gayi bina bataye, divyang hoon chal nahi sakta", "Hisar", "Old-Age / Widow / Disability Pension", "Social Justice & Empowerment", "High", "In Progress", "Disability pension stopped without notice.", 8),

    # --- Roads / streetlights ---
    ("JS-1030", "Gurugram sector 56 road par bade gadde hain, roz accident ho rahe", "Gurugram", "Potholes / Damaged Road", "Public Works (Roads & Buildings)", "High", "Open", "Large potholes causing accidents in Sector 56, Gurugram.", 10),
    ("JS-1031", "Street light kharab hai poori gali andheri rehti hai, mahilaon ko dar lagta hai", "Karnal", "Broken / Missing Streetlight", "Public Works (Roads & Buildings)", "Medium", "Open", "Dark street due to broken streetlight; safety concern for women.", 6),
    ("JS-1032", "सड़क पर गड्ढे की वजह से स्कूल बस फंस जाती है पानीपत में।", "Panipat", "Potholes / Damaged Road", "Public Works (Roads & Buildings)", "Medium", "Open", "School bus stuck due to potholes in Panipat.", 11),

    # --- Sewerage / sanitation ---
    ("JS-1040", "Sewer overflow in front of house faridabad, badbu aur machhar bohot", "Faridabad", "Sewerage Overflow / Blockage", "Public Health Engineering (Water & Sewerage)", "High", "Open", "Sewer overflow causing stench and mosquitoes, Faridabad.", 3),
    ("JS-1041", "कचरा कई दिनों से नहीं उठा, सोनीपत वार्ड 12 में बीमारी फैल रही है।", "Sonipat", "Garbage / Sanitation", "Urban Local Bodies / Municipal", "Medium", "Open", "Uncollected garbage spreading illness, Ward 12 Sonipat.", 5),

    # --- Contaminated water (safety / health) ---
    ("JS-1050", "Nal ka paani ganda aur badbudaar aa raha hai ambala, bachche bimar ho rahe hain", "Ambala", "Contaminated / Dirty Water", "Public Health Engineering (Water & Sewerage)", "High", "Open", "Dirty, smelly tap water making children sick, Ambala.", 4),

    # --- Police / safety ---
    ("JS-1060", "FIR darj nahi ho rahi thaane mein, mere bhai ke saath maarpeet hui", "Rewari", "FIR Not Registered", "Police / Home", "High", "Open", "Police refusing to register FIR after an assault, Rewari.", 2),
    ("JS-1061", "Online fraud ho gaya, kisi ne UPI se 40000 nikaal liye, cyber complaint", "Gurugram", "Cyber / Online Fraud", "Police / Home", "High", "In Progress", "UPI online fraud of Rs 40,000, Gurugram.", 6),

    # --- Revenue / patwari ---
    ("JS-1070", "Patwari intkaal nahi kar raha 6 mahine se, rishwat maang raha hai", "Kaithal", "Mutation (Intkaal) Pending", "Revenue & Disaster Management", "High", "Open", "Mutation pending 6 months; patwari allegedly seeking bribe, Kaithal.", 12),
    ("JS-1071", "Jamabandi mein meri zameen ka record galat chadha hua hai", "Sirsa", "Land Records / Jamabandi Correction", "Revenue & Disaster Management", "Medium", "Open", "Incorrect land record in jamabandi, Sirsa.", 14),

    # --- Health / education ---
    ("JS-1080", "PHC mein dawai nahi milti, doctor bhi nahi aata fatehabad", "Fatehabad", "Medicine / Equipment Shortage", "Health & Family Welfare", "High", "Open", "No medicines and absent doctor at PHC, Fatehabad.", 7),
    ("JS-1081", "Government school mein 2 hi teacher hain 200 bachchon ke liye, jhajjar", "Jhajjar", "Teacher Shortage / Absence", "Education", "Medium", "Open", "Only 2 teachers for 200 students, Jhajjar.", 9),

    # --- Power outage / billing ---
    ("JS-1090", "Roz 6-7 ghante bijli gayab rehti hai garmi mein, yamunanagar", "Yamunanagar", "Power Outage / Supply Failure", "Power / Bijli (UHBVN-DHBVN)", "Medium", "Open", "Daily 6-7 hour power cuts in summer, Yamunanagar.", 3),
    ("JS-1091", "Bijli ka bill 18000 aaya hai jabki ghar 1 month band tha, billing galat", "Panchkula", "Billing Dispute", "Power / Bijli (UHBVN-DHBVN)", "Low", "Open", "Inflated power bill of Rs 18,000 for a vacant house, Panchkula.", 13),

    # --- Ration / PDS ---
    ("JS-1100", "Ration depot wala poora ration nahi deta, BPL card hai phir bhi", "Nuh", "Ration / PDS Shop Issue", "Food, Civil Supplies & Consumer Affairs", "Medium", "Open", "PDS dealer giving short ration despite BPL card, Nuh.", 8),

    # --- Stray animals / municipal ---
    ("JS-1110", "Awara pashu sadak par ghoomte hain, accident ka dar hai kurukshetra", "Kurukshetra", "Stray Animals", "Urban Local Bodies / Municipal", "Medium", "Open", "Stray cattle on roads risking accidents, Kurukshetra.", 10),

    # --- Appreciation (sentiment variety) ---
    ("JS-1120", "Thank you, mera pension ka issue 4 din mein solve ho gaya, bahut acchi service", "Hisar", "Old-Age / Widow / Disability Pension", "Social Justice & Empowerment", "Low", "Resolved", "Citizen thanks dept for resolving pension in 4 days.", 1),
]


def _is_safety_critical(text: str) -> bool:
    low = text.lower()
    return any(sig.lower() in low for sig in SAFETY_CRITICAL_SIGNALS)


def seed_records() -> list[dict]:
    out = []
    for cid, text, dist, cat, dept, urg, status, summary, days in _RAW:
        out.append({
            "complaint_id": cid,
            "text": text,
            "district": dist,
            "category": cat,
            "department": dept,
            "urgency": urg,
            "status": status,
            "summary": summary,
            "created_at": _d(days),
            "source": "historical_seed",
            "is_safety_critical": _is_safety_critical(text),
        })
    return out
