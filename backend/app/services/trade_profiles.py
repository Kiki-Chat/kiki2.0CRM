"""Trade profiles — make the agent universal across crafts/genres.

The org's free-text trade (chosen at onboarding, editable in Kiki-Zentrale) is
resolved to a canonical profile that supplies trade-appropriate:
  • diagnostic follow-up questions (Schritt 1 of the inbound prompt),
  • simple/safe self-help checks,
  • default emergency keywords (only a FALLBACK — an org can still set its own).

Anything we don't recognise falls back to a solid GENERIC profile, so a locksmith,
caterer or IT firm is never shown plumbing examples. Curated taxonomy + generic
fallback (Amber's choice 2026-06-22). Per-org overrides (problem_description,
conversation_logic, emergency_keywords, knowledge_text) still win on top of this.

Keep entries SHORT (1–3 diagnostics, 0–2 self-help, 2–4 emergency keywords) and
SAFE — never suggest a self-help step that could hurt the caller; when unsure, omit
it and let the generic "describe it further" path handle it.
"""
from __future__ import annotations

# Each profile: label (German), match-substrings (lowercased, on the org trade),
# diagnostics, selfhelp (may be empty), emergency (keyword fallbacks).
TRADE_PROFILES: dict[str, dict] = {
    "shk": {
        "label": "Sanitär / Heizung / Klima",
        "match": ["sanitär", "sanitaer", "heizung", "klima", "shk", "klempner",
                  "installateur", "bad", "lüftung", "lueftung", "gas", "therme"],
        "diagnostics": [
            "„Tropft oder läuft irgendwo Wasser aus?“",
            "„Kommt warmes Wasser bzw. wird die Heizung warm?“",
            "„Zeigt das Gerät eine Fehleranzeige oder einen Code?“",
        ],
        "selfhelp": [
            "„Prüf bitte einmal den Druck am Manometer — ist er im grünen Bereich?“",
            "„Hast du schon versucht, den Heizkörper zu entlüften?“",
        ],
        "emergency": [
            "Rohrbruch / unkontrolliert austretendes Wasser",
            "Kompletter Heizungsausfall",
            "Kompletter Warmwasserausfall",
            "Gasgeruch",
        ],
    },
    "elektro": {
        "label": "Elektro / Elektrotechnik",
        "match": ["elektr", "elektriker", "elektrotechnik", "strom", "pv",
                  "photovoltaik", "smart home"],
        "diagnostics": [
            "„Hat ein Sicherungsautomat ausgelöst?“",
            "„Betrifft es nur eine Steckdose oder den ganzen Raum?“",
            "„Riecht es irgendwo verschmort?“",
        ],
        "selfhelp": [
            "„Wirf einen Blick auf den Sicherungskasten — ist eine Sicherung rausgesprungen?“",
        ],
        "emergency": [
            "Kabelbrand / Brandgeruch aus einer Steckdose",
            "Kompletter Stromausfall",
            "Stromschlag / freiliegende Leitung",
        ],
    },
    "dach": {
        "label": "Dachdecker / Bedachung",
        "match": ["dach", "bedachung", "spengler", "flachdach"],
        "diagnostics": [
            "„Seit wann ist es undicht?“",
            "„Tritt aktuell Wasser ins Gebäude ein?“",
            "„Sind nach Wind/Sturm Teile sichtbar lose?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Akuter Wassereintritt ins Gebäude",
            "Sturmschaden / lose Dachteile",
        ],
    },
    "fenster_glas": {
        "label": "Fenster / Glas",
        "match": ["fenster", "glas", "glaser", "verglasung", "rollladen", "rolllaeden"],
        "diagnostics": [
            "„Ist eine Scheibe gebrochen oder nur undicht/klemmend?“",
            "„Lässt sich das Fenster/die Tür noch sicher schließen?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Zerbrochene Scheibe — Gebäude nicht mehr gesichert",
            "Einbruchschaden",
        ],
    },
    "schluessel": {
        "label": "Schlüsseldienst / Schließtechnik",
        "match": ["schlüssel", "schluessel", "schließ", "schliess", "aufsperr"],
        "diagnostics": [
            "„Bist du ausgesperrt oder klemmt das Schloss?“",
            "„Steckt der Schlüssel noch oder ist er abgebrochen?“",
            "„Ist eine Person oder ein Tier eingeschlossen?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Eingeschlossene Person (besonders Kind / pflegebedürftig)",
            "Einbruch / Tür nicht verschließbar",
        ],
    },
    "tischler": {
        "label": "Tischler / Schreiner",
        "match": ["tischler", "schreiner", "möbel", "moebel", "holz", "innenausbau"],
        "diagnostics": [
            "„Um welches Möbel- oder Bauteil geht es?“",
            "„Lässt sich Tür/Schublade/Fenster noch bedienen?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Tür/Fenster lässt sich nicht mehr sichern",
        ],
    },
    "maler": {
        "label": "Maler / Lackierer",
        "match": ["maler", "lackier", "anstrich", "tapezier", "verputz", "stuck"],
        "diagnostics": [
            "„Geht es um eine Innen- oder Außenfläche?“",
            "„Um welchen Raum bzw. wie groß ist die Fläche ungefähr?“",
            "„Ist Schimmel oder Feuchtigkeit sichtbar?“",
        ],
        "selfhelp": [],
        "emergency": [],
    },
    "boden": {
        "label": "Bodenleger / Estrich",
        "match": ["boden", "estrich", "parkett", "fliesen", "fliesenleger", "laminat", "teppich"],
        "diagnostics": [
            "„Um welchen Belag geht es?“",
            "„Gibt es einen Wasserschaden am Boden?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Wasserschaden am Boden",
        ],
    },
    "maurer": {
        "label": "Maurer / Hoch- und Tiefbau",
        "match": ["maurer", "beton", "hochbau", "tiefbau", "rohbau", "bau "],
        "diagnostics": [
            "„Sind Risse oder Setzungen sichtbar?“",
            "„Geht es um tragende Bauteile?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Einsturzgefahr / sichtbarer Statikschaden",
        ],
    },
    "metall": {
        "label": "Metallbau / Schlosserei",
        "match": ["metall", "schlosser", "schweiß", "schweiss", "stahl", "geländer", "gelaender", "tor"],
        "diagnostics": [
            "„Um welches Bauteil geht es (Tor, Geländer, Treppe …)?“",
            "„Ist die Sicherheit/Standfestigkeit beeinträchtigt?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Tor/Geländer/Treppe nicht mehr standsicher",
        ],
    },
    "garten": {
        "label": "Garten- und Landschaftsbau",
        "match": ["garten", "galabau", "landschaft", "baum", "grün", "gruen", "pflaster"],
        "diagnostics": [
            "„Um welche Fläche oder Arbeit geht es?“",
            "„Gibt es einen Sturm- oder Baumschaden?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Umgestürzter Baum / akute Gefahr durch lose Äste",
        ],
    },
    "kfz": {
        "label": "Kfz / Fahrzeugtechnik",
        "match": ["kfz", "auto", "fahrzeug", "werkstatt", "mechaniker", "mechatronik", "reifen", "karosserie"],
        "diagnostics": [
            "„Springt das Fahrzeug an bzw. ist es noch fahrbereit?“",
            "„Leuchtet eine Warnleuchte im Display?“",
            "„Stehest du sicher oder bist du liegengeblieben?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Panne / liegengeblieben im Verkehr",
            "Bremsen oder Lenkung defekt",
            "Unfall",
        ],
    },
    "geraete": {
        "label": "Haushaltsgeräte / Weiße Ware",
        "match": ["gerät", "geraet", "haushaltsgeräte", "weiße ware", "weisse ware",
                  "waschmaschine", "kühl", "kuehl", "spülmaschine", "spuelmaschine"],
        "diagnostics": [
            "„Um welches Gerät geht es?“",
            "„Zeigt das Display einen Fehlercode?“",
            "„Läuft irgendwo Wasser aus?“",
        ],
        "selfhelp": [],
        "emergency": [
            "Wasseraustritt aus dem Gerät",
            "Rauch- oder Brandgeruch",
        ],
    },
    "it": {
        "label": "IT / Elektronik",
        "match": ["it", "edv", "computer", "netzwerk", "elektronik", "software", "telekommunikation"],
        "diagnostics": [
            "„Um welches Gerät oder System geht es?“",
            "„Seit wann besteht das Problem?“",
            "„Wird eine Fehlermeldung angezeigt?“",
        ],
        "selfhelp": [
            "„Hast du das Gerät schon einmal neu gestartet?“",
        ],
        "emergency": [],
    },
    "reinigung": {
        "label": "Reinigung / Gebäudeservice",
        "match": ["reinigung", "gebäudereinig", "gebaeudereinig", "putz", "facility", "hausmeister"],
        "diagnostics": [
            "„Um welches Objekt bzw. welche Fläche geht es?“",
            "„Einmalige Reinigung oder regelmäßig?“",
        ],
        "selfhelp": [],
        "emergency": [],
    },
}

# The catch-all profile — used when the org's trade doesn't match any above.
GENERIC_PROFILE: dict = {
    "label": "Handwerk / Dienstleistung",
    "diagnostics": [
        "„Kannst du das Problem genauer beschreiben — was genau funktioniert nicht?“",
        "„Seit wann besteht das Problem?“",
        "„Ist etwas beschädigt oder sicherheitsrelevant?“",
    ],
    "selfhelp": [],
    "emergency": [
        "Akute Gefahr für Personen",
        "Wasser-, Strom- oder Brandgefahr",
    ],
}


def resolve_trade(free_text: str | None) -> str:
    """Map the org's free-text trade to a canonical profile key (or 'generic')."""
    t = (free_text or "").strip().lower()
    if not t:
        return "generic"
    for key, prof in TRADE_PROFILES.items():
        if any(m in t for m in prof["match"]):
            return key
    return "generic"


def trade_profile(free_text: str | None) -> dict:
    """Resolved profile dict for the org's trade (generic fallback)."""
    key = resolve_trade(free_text)
    return TRADE_PROFILES[key] if key in TRADE_PROFILES else GENERIC_PROFILE


def _bullets(items: list[str]) -> str:
    """3-space-indented bullet lines to match the Schritt-1 template indentation."""
    return "\n".join(f"   - {x}" for x in items)


def render_trade_diagnostics(free_text: str | None) -> str:
    """Bullet list of trade-appropriate diagnostic questions (Schritt 1, point 2)."""
    return _bullets(trade_profile(free_text)["diagnostics"])


def render_trade_selfhelp(free_text: str | None) -> str:
    """Bullet list of safe self-help checks; a neutral fallback line when the trade
    has no safe quick check (so the template's point 3 is never empty)."""
    items = trade_profile(free_text).get("selfhelp") or []
    if not items:
        return (
            "   - Wo es sicher und einfach möglich ist, schlage einen simplen "
            "Selbst-Check vor; sonst direkt zur Terminaufnahme."
        )
    return _bullets(items)


def default_emergency_keywords(free_text: str | None) -> list[str]:
    """Trade-aware fallback emergency keywords (used only when the org hasn't
    configured its own emergency_keywords)."""
    return list(trade_profile(free_text).get("emergency") or GENERIC_PROFILE["emergency"])
