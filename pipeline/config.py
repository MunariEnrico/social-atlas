"""Static configuration: cities, categories, keyword rules, file locations."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB = DATA / "db"
SITE_DATA = ROOT / "site" / "data"

SOURCES_FILE = DATA / "sources.yaml"
ACCOUNTS_FILE = DATA / "accounts.yaml"
CURATED_DIR = DATA / "curated"
OVERRIDES_FILE = DATA / "overrides.yaml"
SUBMISSIONS_FILE = DATA / "submissions.yaml"

EVENTS_DB = DB / "events.json"
SIGNALS_DB = DB / "signals.json"
SOURCE_STATE_DB = DB / "source_state.json"
RUNS_DB = DB / "runs.json"
BRIEFINGS_DIR = DB / "briefings"

MAX_RUNS_KEPT = 120
SIGNAL_RETENTION_DAYS = 120
PAST_EVENT_ARCHIVE_DAYS = 400  # past events stay in the archive this long

# Order matters: this is the display order everywhere.
CITIES = {
    "luxembourg": {
        "name": "Luxembourg", "tz": "Europe/Luxembourg", "currency": "EUR", "country": "LU",
        "airports": ["LUX"], "flight_code": "LUX",
        "keywords": ["luxembourg", "luxemburg", "lëtzebuerg", "kirchberg", "limpertsberg", "clausen", "grund", "bonnevoie", "esch-sur-alzette", "belval", "mudam", "philharmonie"],
    },
    "venice": {
        "name": "Venice", "tz": "Europe/Rome", "currency": "EUR", "country": "IT",
        "airports": ["VCE", "TSF"], "flight_code": "VCE",
        "keywords": ["venice", "venezia", "venise", "venedig", "mestre", "lido di venezia", "murano", "burano", "giudecca", "biennale", "la fenice", "san marco"],
    },
    "cortina": {
        "name": "Cortina d'Ampezzo", "tz": "Europe/Rome", "currency": "EUR", "country": "IT",
        "airports": [], "flight_code": None,
        "nearest_airports": ["VCE", "TSF", "INN"],
        "keywords": ["cortina", "ampezzo", "tofane", "faloria", "cristallo", "cinque torri", "lagazuoi", "dolomiti", "dolomites"],
    },
    "paris": {
        "name": "Paris", "tz": "Europe/Paris", "currency": "EUR", "country": "FR",
        "airports": ["CDG", "ORY"], "flight_code": "PAR",
        "keywords": ["paris", "parisien", "parisienne", "marais", "saint-germain", "montmartre", "pigalle", "grand palais", "louvre", "pompidou"],
    },
    "nyc": {
        "name": "New York City", "tz": "America/New_York", "currency": "USD", "country": "US",
        "airports": ["JFK", "EWR", "LGA"], "flight_code": "NYC",
        "keywords": ["new york", "nyc", "manhattan", "brooklyn", "queens", "bronx", "staten island", "soho", "tribeca", "williamsburg", "harlem", "chelsea", "les ", "lower east side", "west village", "east village"],
    },
    "london": {
        "name": "London", "tz": "Europe/London", "currency": "GBP", "country": "GB",
        "airports": ["LHR", "LGW", "LCY", "STN", "LTN"], "flight_code": "LON",
        "keywords": ["london", "londres", "soho", "shoreditch", "mayfair", "marylebone", "hackney", "peckham", "covent garden", "king's cross", "southbank", "chelsea", "notting hill", "fitzrovia", "clerkenwell"],
    },
}
CITY_ORDER = list(CITIES)

CATEGORIES = {
    "food": "Restaurants & hospitality",
    "nightlife": "Bars & nightlife",
    "art": "Art & design",
    "culture": "Culture & performance",
    "fashion": "Fashion & luxury",
    "business": "Business & networking",
    "sports": "Sports & outdoors",
    "seasonal": "Seasonal & one-off",
    "design": "Design & architecture",
}

# Keyword rules for deterministic classification (lowercase, multilingual).
CATEGORY_KEYWORDS = {
    "food": ["restaurant", "ristorante", "trattoria", "osteria", "bistro", "bistrot", "brasserie", "chef", "tasting menu", "menu dégustation",
             "supper club", "pop-up dinner", "dinner", "cena", "dîner", "gastronom", "michelin", "bakery", "boulangerie", "pâtisserie",
             "pasticceria", "wine", "vino", "vin ", "degustazione", "dégustation", "tasting", "food", "chocolat", "cuisine", "café", "caffè"],
    "nightlife": ["cocktail", "bar ", " bar", "listening bar", "wine bar", "speakeasy", "club", "nightclub", "dj ", "rooftop", "aperitivo", "apéro", "nightlife"],
    "art": ["exhibition", "exhibit", "mostra", "exposition", "ausstellung", "vernissage", "gallery", "galleria", "galerie", "museum", "museo", "musée",
            "art fair", "biennale", "biennial", "private view", "installation", "installazione", "photograph", "fotograf", "sculpture", "painting", "artist"],
    "design": ["design week", "design", "architecture", "architettura", "architect", "showroom", "furniture", "salone"],
    "culture": ["concert", "concerto", "opera", "ballet", "balletto", "theatre", "theater", "teatro", "théâtre", "festival", "book launch", "talk",
                "lecture", "conferenza", "cinema", "film", "jazz", "recital", "symphony", "philharmon", "orchestra", "dance", "danza"],
    "fashion": ["fashion", "moda", "mode ", "défilé", "sfilata", "runway", "couture", "designer", "boutique", "jewel", "gioiell", "watch", "luxury", "lusso", "luxe", "maison"],
    "business": ["fintech", "startup", "start-up", "investor", "venture", "conference", "summit", "networking", "breakfast", "business", "finance", "bank",
                 "payments", "innovation", "tech week", "keynote", "panel", "meetup", "forum", "hackathon", "pitch"],
    "sports": ["marathon", "run ", "running", "race", "tennis", "ski", "world cup", "coppa del mondo", "cycling", "regatta", "sailing", "match",
               "tournament", "golf", "slope", "piste", "lift", "impianti"],
    "seasonal": ["christmas", "natale", "noël", "weihnacht", "chrëschtmaart", "winterlights", "market", "mercatino", "marché", "new year", "capodanno",
                 "carnival", "carnevale", "halloween", "summer", "terrace", "beach club", "illumination", "lights", "parade", "festa"],
}

OPENING_KEYWORDS = ["opens", "opening", "now open", "just opened", "new restaurant", "new bar", "debut", "launches", "unveils",
                    "apre", "apertura", "inaugura", "inaugurazione", "nuovo ristorante", "nuovo locale", "debutta", "taglio del nastro",
                    "ouvre", "ouverture", "vient d'ouvrir", "nouveau restaurant", "nouvelle adresse", "nouveau bar", "inauguration",
                    "eröffnet", "eröffnung", "neues restaurant"]
EVENT_ANNOUNCE_KEYWORDS = ["pop-up", "popup", "éphémère", "temporary", "one night", "one-night", "residency", "résidence", "guest chef",
                           "takeover", "collaboration", "limited", "festival", "vernissage", "private view", "opening reception",
                           "launch party", "tasting", "supper club", "fashion week", "sfilata", "défilé"]
RETROSPECTIVE_KEYWORDS = ["review:", "recensione", "critique", "what we ate", "best restaurants", "migliori", "meilleurs", "top 10", "guide to", "where to eat", "dove mangiare", "où manger", "recap", "obituary", "dies at", "closed for good", "closing for good", "chiude", "ferme définitivement"]

SOLD_OUT_PATTERNS = ["fully booked", "sold out", "sold-out", "complet", "ausverkaaft", "ausverkauft", "esaurito", "tutto esaurito", "no more spots available", "liste d'attente", "waiting list", "waitlist"]
REGISTRATION_REQUIRED_PATTERNS = ["registration required", "register now", "registration is required", "inscription obligatoire", "inscription requise",
                                  "sur inscription", "iscrizione obbligatoria", "anmeldung erforderlich", "anmeldung obligatorisch", "rsvp required", "on registration"]
RESERVATION_REQUIRED_PATTERNS = ["reservation required", "booking required", "booking essential", "réservation obligatoire", "sur réservation",
                                 "prenotazione obbligatoria", "su prenotazione", "reservierung erforderlich", "advance booking required"]
FREE_PATTERNS = ["free entry", "free admission", "entrée libre", "entrée gratuite", "gratuit", "ingresso libero", "ingresso gratuito", "eintritt frei", "free of charge"]
INVITE_PATTERNS = ["invitation only", "by invitation", "invite-only", "sur invitation", "su invito", "members only", "members-only", "riservato ai soci", "trade only", "professionals only"]
