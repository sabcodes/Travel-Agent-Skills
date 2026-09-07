from typing import List, Dict, Any, Optional

# Chase Ultimate Rewards Airline Partners & Alliances
CHASE_PARTNER_MAP = {
    # Star Alliance
    "united": {
        "partners": ["United MileagePlus", "Air Canada Aeroplan", "Singapore KrisFlyer"],
        "alliance": "Star Alliance",
        "keywords": ["united", "aeroplan", "air canada", "krisflyer", "star alliance"]
    },
    "copa": {
        "partners": ["United MileagePlus", "Air Canada Aeroplan"],
        "alliance": "Star Alliance",
        "keywords": ["united", "aeroplan", "copa"]
    },
    "air canada": {
        "partners": ["Air Canada Aeroplan", "United MileagePlus"],
        "alliance": "Star Alliance",
        "keywords": ["aeroplan", "air canada"]
    },
    "avianca": {
        "partners": ["Avianca LifeMiles", "Air Canada Aeroplan", "United MileagePlus"],
        "alliance": "Star Alliance",
        "keywords": ["lifemiles", "avianca", "aeroplan"]
    },
    # Oneworld (bookable via British Airways / Iberia Avios)
    "american": {
        "partners": ["British Airways Executive Club", "Iberia Plus"],
        "alliance": "Oneworld",
        "keywords": ["british airways", "iberia", "avios", "american airlines", "aa"]
    },
    "british airways": {
        "partners": ["British Airways Executive Club"],
        "alliance": "Oneworld",
        "keywords": ["british airways", "avios"]
    },
    "iberia": {
        "partners": ["Iberia Plus", "British Airways Executive Club"],
        "alliance": "Oneworld",
        "keywords": ["iberia", "avios"]
    },
    # SkyTeam (bookable via Flying Blue / Virgin Atlantic)
    "delta": {
        "partners": ["Air France / KLM Flying Blue", "Virgin Atlantic Flying Club"],
        "alliance": "SkyTeam",
        "keywords": ["air france", "flying blue", "virgin atlantic", "virgin", "delta"]
    },
    "aeromexico": {
        "partners": ["Air France / KLM Flying Blue", "Virgin Atlantic Flying Club"],
        "alliance": "SkyTeam",
        "keywords": ["air france", "flying blue", "virgin atlantic", "aeromexico"]
    },
    # Direct Chase Partners
    "southwest": {
        "partners": ["Southwest Rapid Rewards"],
        "alliance": "Direct Partner",
        "keywords": ["southwest", "rapid rewards"]
    },
    "jetblue": {
        "partners": ["JetBlue TrueBlue"],
        "alliance": "Direct Partner",
        "keywords": ["jetblue", "trueblue"]
    }
}

def analyze_synergies(
    flights: List[Dict[str, Any]],
    deals: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Cross-references cash flight deals with discovered credit card deals and transfer bonuses.
    Augments flight records with synergy alerts when an airline matches a Chase partner or active bonus.
    """
    synergized_flights = []

    for flight in flights:
        f = dict(flight)
        f_airline = f.get("airline", "").lower()

        matched_partner_info = None
        for airline_key, info in CHASE_PARTNER_MAP.items():
            if airline_key in f_airline:
                matched_partner_info = info
                break

        relevant_deals = []
        if matched_partner_info:
            for deal in deals:
                deal_title = deal.get("title", "").lower()
                deal_keywords = [kw.lower() for kw in deal.get("matched_keywords", [])]

                # Check if deal relates to partner keywords
                matches_deal = any(
                    kw in deal_title or kw in deal_keywords
                    for kw in matched_partner_info["keywords"]
                )
                if matches_deal:
                    relevant_deals.append(deal)

        f["chase_partner_info"] = matched_partner_info
        f["relevant_deals"] = relevant_deals
        f["has_transfer_bonus"] = any(d.get("is_transfer_bonus", False) for d in relevant_deals)

        synergized_flights.append(f)

    return synergized_flights

if __name__ == "__main__":
    sample_flights = [
        {"airline": "United", "price": 491, "origin": "SFO", "destination": "CUN"},
        {"airline": "American", "price": 476, "origin": "SJC", "destination": "SJU"}
    ]
    sample_deals = [
        {"title": "Chase 20% Transfer Bonus to Air Canada Aeroplan", "is_transfer_bonus": True, "matched_keywords": ["aeroplan"]}
    ]
    syn = analyze_synergies(sample_flights, sample_deals)
    print(f"Synergy analysis result: {len(syn)} items")
    for s in syn:
        print(f"Flight {s['airline']}: has_bonus={s['has_transfer_bonus']}, deals={len(s['relevant_deals'])}")
