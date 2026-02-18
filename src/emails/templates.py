"""
Norwegian email templates for Sperton recruitment outreach.

Each template is a function that takes prospect + job posting data
and returns (subject, body) tuple.

Templates are personalised with:
- Prospect name / title
- Company name
- Job posting title and location
- Sperton value proposition
"""


def _first_name_or_fallback(prospect: dict) -> str:
    """Get first name or polite fallback."""
    first = prospect.get("first_name", "").strip()
    if first:
        return first
    full = prospect.get("full_name", "").strip()
    if full:
        return full.split()[0]
    return "Hei"


def _title_line(prospect: dict) -> str:
    """Build a polite title line if we know the person's position."""
    position = prospect.get("position", "").strip()
    if position:
        return f"Jeg ser at du jobber som {position}"
    return "Jeg tar kontakt"


def formal_outreach(prospect: dict, posting: dict) -> tuple[str, str]:
    """
    Template 1: Formal introduction.
    Professional tone — suitable for executives and HR managers.
    """
    name = _first_name_or_fallback(prospect)
    company = prospect.get("company_name", "deres selskap")
    job_title = posting.get("title", "en stilling")
    location = posting.get("location", "")

    location_str = f" i {location}" if location else ""

    subject = f"Rekrutteringspartner for {company} - Sperton"

    body = f"""Hei {name},

Jeg ser at {company} har utlyst stillingen "{job_title}"{location_str}, og vil gjerne presentere Sperton som en potensiell rekrutteringspartner.

Sperton er et spesialisert rekrutteringsbyraa som hjelper norske bedrifter med aa finne de beste kandidatene innen sjoemat, havbruk, industri og teknologi. Vi har et bredt nettverk av kvalifiserte fagfolk og tilbyr:

- Grundig kartlegging av kandidater med relevant bransjeerfaring
- Effektiv rekrutteringsprosess som sparer dere tid og ressurser
- Garanti paa alle plasseringer

Kan vi ta en kort samtale om hvordan Sperton kan bidra til aa fylle denne stillingen? Jeg er tilgjengelig for et uforpliktende moete naar det passer deg.

Med vennlig hilsen,
Sperton Rekruttering
www.sperton.com"""

    return subject, body


def short_intro(prospect: dict, posting: dict) -> tuple[str, str]:
    """
    Template 2: Short and direct intro.
    Casual but professional — good for mid-level contacts.
    """
    name = _first_name_or_fallback(prospect)
    company = prospect.get("company_name", "dere")
    job_title = posting.get("title", "en ny stilling")

    subject = f"Hjelp med rekruttering - {job_title}"

    body = f"""Hei {name},

{_title_line(prospect)} hos {company}, og jeg legger merke til at dere soeker etter "{job_title}".

Sperton spesialiserer seg paa rekruttering innen nettopp dette segmentet. Vi har allerede kandidater i nettverket vaart som kan vaere aktuelle.

Er du aapen for en rask prat om hvordan vi kan hjelpe? Det tar bare 10 minutter.

Beste hilsen,
Sperton Rekruttering
www.sperton.com"""

    return subject, body


def value_proposition(prospect: dict, posting: dict) -> tuple[str, str]:
    """
    Template 3: Value proposition focused.
    Leads with the benefit — good for decision-makers.
    """
    name = _first_name_or_fallback(prospect)
    company = prospect.get("company_name", "deres selskap")
    job_title = posting.get("title", "en stilling")
    location = posting.get("location", "")

    location_str = f" i {location}" if location else ""

    subject = f"Raskere rekruttering for {company}?"

    body = f"""Hei {name},

Visste du at gjennomsnittlig tid for aa fylle en stilling i Norge er over 40 dager? Sperton kutter denne tiden betydelig.

Jeg ser at {company} har publisert "{job_title}"{location_str}. Vaare kunder opplever typisk:

- 50% kortere tid til ansettelse
- Tilgang til passive kandidater som ikke soeker aktivt
- Grundig screening saa dere kun moetar de beste

Vi har spesialisert oss paa rekruttering innen sjoemat, havbruk og relaterte bransjer, og kjenner markedet godt.

Kan jeg sende deg mer informasjon, eller skal vi ta en kort samtale?

Med vennlig hilsen,
Sperton Rekruttering
www.sperton.com"""

    return subject, body


# Registry of all templates — used by drafter to pick which to use
TEMPLATES = {
    "formal_outreach": {
        "fn": formal_outreach,
        "label": "Formell introduksjon",
        "description": "Profesjonell foerstegangs henvendelse med full presentasjon av Sperton",
    },
    "short_intro": {
        "fn": short_intro,
        "label": "Kort introduksjon",
        "description": "Direkte og kort melding med tilbud om en rask prat",
    },
    "value_proposition": {
        "fn": value_proposition,
        "label": "Verdiforslag",
        "description": "Fokus paa gevinster og statistikk for aa overbevise beslutningstakere",
    },
}
