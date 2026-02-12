#!/usr/bin/env python3
"""
Sam.gov Roofing Project Scraper for Alpha Commercial Roofing.

Searches for federal roofing opportunities within 300 miles of Atlanta,
excluding Florida.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

import requests


ATLANTA_COORDS = (33.7490, -84.3880)  # Atlanta, GA coordinates
SEARCH_RADIUS_MILES = 300
SAM_GOV_API_KEY = os.getenv("SAM_GOV_API_KEY", "YOUR_API_KEY_HERE")

# Fully burdened hourly staffing rates.
STAFFING_RATES = {
    "SSHO": 85.00,  # Site Safety and Health Officer
    "RRO": 75.00,  # Registered Roof Observer
    "PM": 95.00,  # Project Manager
    "superintendent": 70.00,
    "foreman": 55.00,
}


def calculate_distance(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
    """Calculate great-circle distance between two latitude/longitude points in miles."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1

    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return 3956 * c


def is_in_florida(location_text: str) -> bool:
    """Check if a location string appears to be in Florida."""
    florida_indicators = [
        "florida",
        "fl,",
        ", fl",
        "fl ",
        "jacksonville",
        "tampa",
        "miami",
        "orlando",
        "tallahassee",
        "pensacola",
    ]
    location_lower = location_text.lower()
    return any(indicator in location_lower for indicator in florida_indicators)


def extract_coordinates(place_of_performance: dict[str, Any] | None) -> tuple[float, float] | None:
    """
    Extract coordinates from place-of-performance data.

    This uses broad state-level approximations unless explicit latitude/longitude
    values are available.
    """
    if not place_of_performance:
        return None

    # Prefer coordinates directly if present.
    try:
        lat = float(place_of_performance.get("latitude"))
        lon = float(place_of_performance.get("longitude"))
        return lat, lon
    except (TypeError, ValueError):
        pass

    state = (place_of_performance.get("state") or {}).get("name", "")
    state_coords = {
        "Georgia": (32.1656, -82.9001),
        "Alabama": (32.3182, -86.9023),
        "Tennessee": (35.5175, -86.5804),
        "South Carolina": (33.8361, -81.1637),
        "North Carolina": (35.7596, -79.0193),
    }
    return state_coords.get(state)


def estimate_staffing_costs(contract_value: float, duration_days: int = 90) -> dict[str, Any]:
    """Estimate staffing costs for a federal roofing project."""
    staffing: dict[str, dict[str, float]] = {}

    ssho_hours = duration_days * 8
    staffing["SSHO"] = {
        "hours": ssho_hours,
        "rate": STAFFING_RATES["SSHO"],
        "cost": ssho_hours * STAFFING_RATES["SSHO"],
    }

    rro_hours = duration_days * 2
    staffing["RRO"] = {
        "hours": rro_hours,
        "rate": STAFFING_RATES["RRO"],
        "cost": rro_hours * STAFFING_RATES["RRO"],
    }

    pm_hours = duration_days * (4 if contract_value > 1_000_000 else 2)
    staffing["PM"] = {
        "hours": pm_hours,
        "rate": STAFFING_RATES["PM"],
        "cost": pm_hours * STAFFING_RATES["PM"],
    }

    total_staffing_cost = sum(role["cost"] for role in staffing.values())
    percent = (total_staffing_cost / contract_value * 100) if contract_value > 0 else 0

    return {
        "breakdown": staffing,
        "total_cost": total_staffing_cost,
        "percent_of_contract": percent,
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert unknown numeric-like values to float safely."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("$", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def search_samgov_opportunities(keywords: str = "roofing", days_back: int = 30) -> list[dict[str, Any]]:
    """Search Sam.gov opportunities endpoint for matching notices."""
    base_url = "https://api.sam.gov/opportunities/v2/search"

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)

    params = {
        "api_key": SAM_GOV_API_KEY,
        "postedFrom": start_date.strftime("%m/%d/%Y"),
        "postedTo": end_date.strftime("%m/%d/%Y"),
        "ptype": "o",
        "limit": 100,
    }
    if keywords:
        params["q"] = keywords

    print(
        f"Searching Sam.gov for '{keywords}' opportunities "
        f"from {start_date.date()} to {end_date.date()}..."
    )

    if SAM_GOV_API_KEY == "YOUR_API_KEY_HERE":
        print("Warning: SAM_GOV_API_KEY is not set. API call is likely to fail.")

    try:
        response = requests.get(base_url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        opportunities = data.get("opportunitiesData", [])

        print(f"Found {len(opportunities)} opportunities")
        return opportunities
    except requests.exceptions.RequestException as exc:
        print(f"Error connecting to Sam.gov API: {exc}")
        print("You need an API key from https://open.gsa.gov/api/opportunities-api/")
        print("Set it as: export SAM_GOV_API_KEY='your_key_here'")
        return []


def filter_opportunities(opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Filter opportunities based on ACR criteria:
    - Within 300 miles of Atlanta
    - Not in Florida
    - Roofing-related
    """
    filtered: list[dict[str, Any]] = []
    roofing_keywords = ["roof", "roofing", "membrane", "waterproofing", "shingle"]

    for opp in opportunities:
        title = opp.get("title", "") or ""
        notice_id = opp.get("noticeId", "") or ""
        description = opp.get("description", "") or ""

        text_to_search = f"{title} {description}".lower()
        is_roofing = any(keyword in text_to_search for keyword in roofing_keywords)
        if not is_roofing:
            continue

        place = opp.get("placeOfPerformance", {}) or {}
        city = (place.get("city") or {}).get("name", "")
        state = (place.get("state") or {}).get("name", "")
        location_str = f"{city}, {state}".strip(", ")

        if is_in_florida(location_str):
            print(f"EXCLUDED (Florida): {title}")
            continue

        coords = extract_coordinates(place)
        distance: float | None = None
        if coords:
            distance = calculate_distance(ATLANTA_COORDS, coords)
            if distance > SEARCH_RADIUS_MILES:
                print(f"EXCLUDED (too far - {distance:.0f} miles): {title}")
                continue

        award_amount = _safe_float(((opp.get("award") or {}).get("amount")))
        contract_value_for_estimate = award_amount if award_amount > 0 else 500000
        staffing = estimate_staffing_costs(contract_value_for_estimate)

        filtered_opp = {
            "notice_id": notice_id,
            "title": title,
            "posted_date": opp.get("postedDate", ""),
            "response_deadline": opp.get("responseDeadLine", ""),
            "location": location_str,
            "distance_from_atlanta": f"{distance:.0f} miles" if distance is not None else "Unknown",
            "naics_code": opp.get("naicsCode", ""),
            "set_aside": opp.get("typeOfSetAside", "None"),
            "contract_value": f"${award_amount:,.0f}" if award_amount > 0 else "Not specified",
            "staffing_cost": f"${staffing['total_cost']:,.0f}",
            "staffing_percent": f"{staffing['percent_of_contract']:.1f}%",
            "ssho_hours": staffing["breakdown"]["SSHO"]["hours"],
            "rro_hours": staffing["breakdown"]["RRO"]["hours"],
            "pm_hours": staffing["breakdown"]["PM"]["hours"],
            "url": f"https://sam.gov/opp/{notice_id}/view",
            "description_preview": f"{description[:200]}..." if len(description) > 200 else description,
        }

        filtered.append(filtered_opp)
        print(f"QUALIFIED: {title} ({location_str})")

    return filtered


def export_to_csv(opportunities: list[dict[str, Any]], filename: str = "samgov_opportunities.csv") -> None:
    """Export opportunities to CSV."""
    if not opportunities:
        print("No opportunities to export.")
        return

    fieldnames = list(opportunities[0].keys())
    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(opportunities)

    print(f"\nExported {len(opportunities)} opportunities to {filename}")


def generate_report(opportunities: list[dict[str, Any]]) -> None:
    """Generate a terminal summary report."""
    print("\n" + "=" * 80)
    print("ALPHA COMMERCIAL ROOFING - SAM.GOV OPPORTUNITY REPORT")
    print("=" * 80)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Search Criteria: Within {SEARCH_RADIUS_MILES} miles of Atlanta, GA (excluding Florida)")
    print(f"Total Qualified Opportunities: {len(opportunities)}")
    print("=" * 80)

    if not opportunities:
        print("\nNo opportunities found matching criteria.")
        print("Try adjusting search parameters or check back later.")
        return

    print("\nQUALIFIED OPPORTUNITIES:")
    for idx, opp in enumerate(opportunities, start=1):
        print(f"\n{idx}. {opp['title']}")
        print(f"   Notice ID: {opp['notice_id']}")
        print(f"   Location: {opp['location']} ({opp['distance_from_atlanta']})")
        print(f"   Response Deadline: {opp['response_deadline']}")
        print(f"   Contract Value: {opp['contract_value']}")
        print(f"   Estimated Staffing Cost: {opp['staffing_cost']} ({opp['staffing_percent']} of contract)")
        print(f"   Required Hours: SSHO={opp['ssho_hours']}, RRO={opp['rro_hours']}, PM={opp['pm_hours']}")
        print(f"   Set-Aside: {opp['set_aside']}")
        print(f"   URL: {opp['url']}")
        print(f"   Preview: {opp['description_preview']}")


def main() -> None:
    """Main execution function."""
    print("=" * 80)
    print("SAM.GOV ROOFING PROJECT SCRAPER")
    print("Alpha Commercial Roofing - Federal Opportunity Finder")
    print("=" * 80)

    opportunities = search_samgov_opportunities(keywords="roofing", days_back=30)
    filtered = filter_opportunities(opportunities)
    generate_report(filtered)

    if filtered:
        export_to_csv(filtered, "acr_qualified_opportunities.csv")

    print("\n" + "=" * 80)
    print("NEXT STEPS:")
    print("1. Review the qualified opportunities in the CSV file.")
    print("2. Visit the URLs to read full solicitations.")
    print("3. Determine if you have the capacity and capability.")
    print("4. Begin proposal preparation for high-priority targets.")
    print("=" * 80)


if __name__ == "__main__":
    main()
