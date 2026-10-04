"""Norwegian LinkedIn message templates for multichannel outreach.

Connection requests: max 300 characters.
Follow-up messages: after connection accepted, longer pitch.
InMail: premium feature, can be longer.
"""


def connection_request(prospect: dict, posting: dict = None) -> str:
    """Short LinkedIn connection request (max 300 chars).

    Personal, references job posting, professional tone.
    """
    first_name = prospect.get("first_name") or (prospect.get("full_name", "").split()[0] if prospect.get("full_name") else "")
    company = prospect.get("company_name", "")
    job_title = (posting or {}).get("title", "")

    if job_title:
        msg = (
            f"Hei {first_name}, jeg ser at {company} soker etter {job_title}. "
            f"Sperton har 20+ aars erfaring med spesialisert rekruttering innen deres bransje. "
            f"Aapne for en kort prat?"
        )
    else:
        msg = (
            f"Hei {first_name}, jeg jobber med rekruttering og bemanning for selskaper som {company}. "
            f"Sperton har et nettverk paa 70 000+ spesialister i 140+ land. "
            f"Alltid interessert i aa utvide nettverket."
        )

    # Ensure max 300 chars for connection request
    if len(msg) > 300:
        msg = msg[:297] + "..."

    return msg


def follow_up_message(prospect: dict, posting: dict = None) -> str:
    """LinkedIn follow-up after connection accepted."""
    first_name = prospect.get("first_name") or (prospect.get("full_name", "").split()[0] if prospect.get("full_name") else "")
    company = prospect.get("company_name", "")
    position = prospect.get("position", prospect.get("prospect_title", ""))

    msg = f"""Takk for kontakten, {first_name}!

Som nevnt jobber jeg i Sperton Rekruttering, og vi spesialiserer oss paa aa finne noekkelpersoner for bedrifter som {company}.

Vi har over 20 aars erfaring og ISO 9001:2015-sertifisering, og vi opererer i 140+ land. Vaart team forstaar utfordringene med aa finne riktig kompetanse i et konkurransepreget marked.

Jeg vil gjerne hore mer om {company}s behov — har du tid til 10 minutter denne uken?

Mvh,
Fredrik Hansen
Sperton Rekruttering"""

    return msg


def inmail_message(prospect: dict, posting: dict = None) -> str:
    """LinkedIn InMail — can be longer, used for premium outreach."""
    first_name = prospect.get("first_name") or (prospect.get("full_name", "").split()[0] if prospect.get("full_name") else "")
    company = prospect.get("company_name", "")
    job_title = (posting or {}).get("title", "")

    if job_title:
        opening = f"Jeg la merke til at {company} soker etter {job_title}, og tenkte det kunne vaere interessant aa ta kontakt."
    else:
        opening = f"Jeg onsker aa ta kontakt angaaende {company}s rekrutteringsbehov."

    msg = f"""Hei {first_name},

{opening}

Sperton Rekruttering har i over 20 aar hjulpet selskaper som {company} med aa finne spesialiserte kandidater. Vi er ISO 9001:2015-sertifisert og har et nettverk paa over 70 000 fagfolk i 140+ land.

Noen av vaare styrker:
- Dype bransjenettverk innen energi, maritim, sjomat, IT og logistikk
- Rask levering — typisk 2-4 uker til shortlist
- Garanti paa alle plasseringer

Ville det passet med en uforpliktende samtale i loepet av uken?

Med vennlig hilsen,
Fredrik Hansen
Sperton Rekruttering"""

    return msg


LINKEDIN_TEMPLATES = {
    "connection_request": connection_request,
    "follow_up": follow_up_message,
    "inmail": inmail_message,
}
