"""A small safety net that does not depend on the model.

If she mentions an emergency sign or a likely scam, the screen shows a big card with
the emergency contact, no matter what the model says. Keyword lists are deliberately
simple and err on the side of showing the card.
"""
import re
import unicodedata

EMERGENCY = [
    "सीने में दर्द", "छाती में दर्द", "दिल में दर्द", "दिल का दौरा",
    "गिर गई", "गिर गया", "गिर पड़ी", "गिर पड़ा", "उठ नहीं पा",
    "सांस नहीं", "सांस लेने में", "सांस फूल", "दम घुट",
    "बेहोश", "चक्कर आ", "बहुत तेज़ दर्द", "बहुत दर्द", "खून बह",
    "लकवा", "बोल नहीं पा", "हाथ सुन्न", "मुंह टेढ़ा",
    "chest pain", "heart attack", "i fell", "can't breathe", "cannot breathe",
    "fainted", "bleeding", "stroke", "ambulance", "एम्बुलेंस", "एंबुलेंस",
]

SCAM = [
    "otp", "ओटीपी", "ओ टी पी", "पिन नंबर", "पासवर्ड", "अकाउंट नंबर", "खाता नंबर",
    "कार्ड नंबर", "cvv", "kyc", "केवाईसी", "के वाई सी", "लॉटरी", "इनाम जीत",
    "बैंक से फोन", "बैंक वाले", "पैसे भेज", "पैसे ट्रांसफर", "upi pin", "यूपीआई पिन",
    "anydesk", "एनीडेस्क", "teamviewer", "गिरफ्तार", "डिजिटल अरेस्ट", "digital arrest",
]


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    text = text.replace("़", "")        # nukta: ड़ -> ड, ज़ -> ज
    text = text.replace("ँ", "ं")  # chandrabindu -> anusvara: साँस -> सांस
    return re.sub(r"\s+", " ", text)


_EMERGENCY = [_normalise(k) for k in EMERGENCY]
_SCAM = [_normalise(k) for k in SCAM]


def check(text: str) -> str | None:
    """Return 'emergency', 'scam' or None."""
    t = _normalise(text or "")
    if any(k in t for k in _EMERGENCY):
        return "emergency"
    if any(k in t for k in _SCAM):
        return "scam"
    return None
