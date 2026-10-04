"""Norwegian follow-up email templates for automated sequences.

Step 2: Gentle nudge (3 days after no open)
Step 3: Different angle with social proof (6 days after step 2)
"""


def follow_up_1(prospect: dict, original_subject: str) -> tuple[str, str]:
    """Step 2 — gentle nudge, references original email."""
    first_name = (
        prospect.get("first_name") or prospect.get("full_name", "").split()[0]
        if prospect.get("full_name")
        else ""
    )
    company = prospect.get("company_name", "")

    subject = f"Re: {original_subject}"
    body = f"""Hei {first_name},

Jeg ville bare forsikre meg om at du mottok min forrige melding. Jeg forstaar at det er travelt, men jeg tror vi kan bidra med noe verdifullt for {company}.

Kort oppsummert: Sperton har over 20 aars erfaring med aa finne spesialiserte kandidater innen deres bransje. Vi har et nettverk paa over 70 000 fagfolk i 140+ land.

Har du 10 minutter til en uforpliktende samtale denne uken?

Med vennlig hilsen,
Fredrik Hansen
Sperton Rekruttering
+47 XXX XX XXX"""

    return subject, body


def follow_up_2(prospect: dict, original_subject: str) -> tuple[str, str]:
    """Step 3 — different angle, value-add with social proof."""
    first_name = (
        prospect.get("first_name") or prospect.get("full_name", "").split()[0]
        if prospect.get("full_name")
        else ""
    )
    company = prospect.get("company_name", "")

    subject = f"Re: {original_subject}"
    body = f"""Hei {first_name},

Jeg prover en siste gang — jeg vet at rekruttering sjelden er topp prioritet helt til det plutselig haster.

Mange av vaare kunder i lignende bransjer som {company} har oppdaget at det aa ha en rekrutteringspartner paa plass FOR behovet oppstaar gjor hele prosessen raskere og billigere.

Et par eksempler:
- Redusert tid-til-ansettelse med 40% for en kunde innen energisektoren
- Funnet 3 noekkelpersoner paa under 4 uker for et sjoematselskap

Uansett om det er aktuelt naa eller senere — jeg er tilgjengelig for en kort prat naar det passer.

Beste hilsen,
Fredrik Hansen
Sperton Rekruttering
+47 XXX XX XXX"""

    return subject, body


FOLLOW_UP_TEMPLATES = {
    2: follow_up_1,
    3: follow_up_2,
}
