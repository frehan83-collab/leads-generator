"""Sperton industry-specific value propositions for AI-powered email personalization.

Maps NACE codes and keywords to relevant Sperton expertise descriptions,
used to enrich AI-generated email openers with company-specific context.
"""

# Sperton's key service areas with Norwegian descriptions
INDUSTRY_CONTEXT = {
    "seafood": (
        "Sperton har lang erfaring med rekruttering innen sjoemat og havbruk. "
        "Vi forstaar bransjens unike utfordringer med sesongvariasjoner, "
        "regulatoriske krav og behovet for spesialisert kompetanse innen "
        "oppdrett, foredling og eksport."
    ),
    "aquaculture": (
        "Innen akvakultur har Sperton et sterkt nettverk av fagfolk som dekker "
        "alt fra RAS-teknologi og smoltproduksjon til fiskehelse og "
        "lokalitetsledelse. Vi har plassert hundrevis av kandidater i sektoren."
    ),
    "energy": (
        "Med 20+ aars erfaring innen energisektoren forstaar Sperton behovet for "
        "hoeyt kvalifiserte ingeniorer, prosjektledere og HSE-personell. "
        "Vi dekker olje og gass, fornybar energi og kraftproduksjon."
    ),
    "oil_gas": (
        "Sperton har vaert en noekkelleverandoer av bemanning til olje- og "
        "gassindustrien i over to tiaar. Vi leverer alt fra boreteknisk personell "
        "til ledelsesteam for offshore- og onshore-prosjekter."
    ),
    "maritime": (
        "Sperton har spesialkompetanse innen maritim sektor, inkludert skipsfart, "
        "verft og marine operasjoner. Vi rekrutterer navigatoerer, ingeniorer, "
        "og ledelsesteam med internasjonal erfaring."
    ),
    "it": (
        "Vi forstaar teknologibransjens behov for rask tilgang til utviklere, "
        "arkitekter, prosjektledere og IT-ledere. Sperton kombinerer teknisk "
        "forstaelse med et globalt nettverk for effektiv IT-rekruttering."
    ),
    "logistics": (
        "Innen logistikk og supply chain har Sperton erfaring med aa bemanne "
        "komplekse verdikjeder. Vi finner lager-, transport- og innkjoepsledere "
        "med bransjespesifikk kompetanse."
    ),
    "construction": (
        "Sperton bistaar bygge- og anleggsbransjen med aa finne prosjektledere, "
        "ingeniorer og HMS-personell. Vi forstaar bransjens krav til "
        "sertifiseringer og praktisk erfaring."
    ),
    "finance": (
        "For finans- og banknaaeringen leverer Sperton okonomer, revisorer, "
        "compliance-eksperter og ledere med solid erfaring fra regulerte miljøoer."
    ),
    "healthcare": (
        "Innen helse og farmasi rekrutterer Sperton leger, sykepleiere, "
        "forskere og administratorer med forstaelse for strenge regulatoriske krav."
    ),
}

# Map common NACE codes to our industry keys
NACE_TO_INDUSTRY = {
    "03": "seafood",        # Fishing and aquaculture
    "03.1": "seafood",
    "03.2": "aquaculture",
    "03.21": "aquaculture",
    "06": "oil_gas",        # Extraction of crude petroleum and gas
    "09": "oil_gas",        # Mining support services
    "10": "seafood",        # Food manufacturing (often seafood)
    "10.2": "seafood",      # Processing of fish
    "19": "energy",         # Petroleum products
    "35": "energy",         # Electricity, gas, steam
    "41": "construction",   # Building construction
    "42": "construction",   # Civil engineering
    "43": "construction",   # Specialized construction
    "49": "logistics",      # Land transport
    "50": "maritime",       # Water transport
    "52": "logistics",      # Warehousing
    "62": "it",             # Computer programming
    "63": "it",             # Information services
    "64": "finance",        # Financial services
    "65": "finance",        # Insurance
    "66": "finance",        # Other financial activities
    "86": "healthcare",     # Human health
    "87": "healthcare",     # Residential care
}

# Map keywords to industry keys
KEYWORD_TO_INDUSTRY = {
    "seafood": "seafood",
    "sjoemat": "seafood",
    "sjomat": "seafood",
    "fisk": "seafood",
    "aquaculture": "aquaculture",
    "akvakultur": "aquaculture",
    "oppdrett": "aquaculture",
    "smolt": "aquaculture",
    "ras": "aquaculture",
    "fiskehelse": "aquaculture",
    "rokter": "aquaculture",
    "matfisk": "aquaculture",
    "energy": "energy",
    "energi": "energy",
    "oil": "oil_gas",
    "olje": "oil_gas",
    "gass": "oil_gas",
    "offshore": "oil_gas",
    "maritim": "maritime",
    "maritime": "maritime",
    "shipping": "maritime",
    "skipsfart": "maritime",
    "it": "it",
    "software": "it",
    "tech": "it",
    "teknologi": "it",
    "logistikk": "logistics",
    "logistics": "logistics",
    "transport": "logistics",
    "bygg": "construction",
    "construction": "construction",
    "anlegg": "construction",
    "finans": "finance",
    "bank": "finance",
    "helse": "healthcare",
    "pharma": "healthcare",
    "eksport": "seafood",
    "foredling": "seafood",
    "produksjon": "seafood",
}


def get_industry_context(nace_code: str = None, keyword: str = None) -> str:
    """Get Sperton's relevant value proposition for a given industry.

    Args:
        nace_code: NACE code from BRREG (e.g., '03.21', '62.01')
        keyword: Job posting keyword (e.g., 'seafood', 'oppdrett')

    Returns:
        Industry-specific Sperton value proposition string, or a generic one.
    """
    industry_key = None

    # Try NACE code first (more specific)
    if nace_code:
        # Try exact match, then prefix matches
        for prefix_len in [5, 4, 3, 2]:
            prefix = nace_code[:prefix_len].rstrip(".")
            if prefix in NACE_TO_INDUSTRY:
                industry_key = NACE_TO_INDUSTRY[prefix]
                break

    # Fall back to keyword match
    if not industry_key and keyword:
        kw_lower = keyword.lower().strip()
        if kw_lower in KEYWORD_TO_INDUSTRY:
            industry_key = KEYWORD_TO_INDUSTRY[kw_lower]
        else:
            # Partial match
            for kw_map, ind_key in KEYWORD_TO_INDUSTRY.items():
                if kw_map in kw_lower or kw_lower in kw_map:
                    industry_key = ind_key
                    break

    if industry_key and industry_key in INDUSTRY_CONTEXT:
        return INDUSTRY_CONTEXT[industry_key]

    # Generic fallback
    return (
        "Sperton er et globalt rekrutteringsfirma med over 20 aars erfaring, "
        "ISO 9001:2015-sertifisering og et nettverk paa over 70 000 spesialister "
        "i 140+ land. Vi hjelper bedrifter med aa finne riktig kompetanse raskt."
    )
