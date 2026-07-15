# maps_server.py
import logging
import os
import re

import googlemaps
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
logging.basicConfig(level=logging.WARNING)  # silence googlemaps/MCP per-request INFO logs

mcp = FastMCP("Maps")
gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))


def _strip_html(text: str) -> str:
    return re.sub("<[^<]+?>", "", text)


@mcp.tool()
def get_directions(origin: str, destination: str) -> str:
    """Get driving distance, duration, and turn-by-turn directions between two places (addresses or city names)."""
    routes = gmaps.directions(origin, destination, mode="driving")
    if not routes:
        return f"No route found between {origin} and {destination}."

    leg = routes[0]["legs"][0]
    steps = [_strip_html(s["html_instructions"]) for s in leg["steps"]]
    header = f"Distance: {leg['distance']['text']}, Duration: {leg['duration']['text']}"
    body = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    return f"{header}\n{body}"


@mcp.tool()
def find_stopovers(
    origin: str,
    destination: str,
    place_type: str = "restaurant",
    interval_km: int = 100,
) -> str:
    """Find places (place_type e.g. 'restaurant', 'gas_station', 'tourist_attraction', 'lodging')
    roughly every interval_km along the driving route between origin and destination.
    Useful for planning stopovers on a road trip."""
    routes = gmaps.directions(origin, destination, mode="driving")
    if not routes:
        return f"No route found between {origin} and {destination}."

    leg = routes[0]["legs"][0]
    total_km = leg["distance"]["value"] / 1000
    if total_km == 0:
        return "Origin and destination appear to be the same place."

    # The route is returned as an encoded polyline (a compressed list of lat/lng
    # points tracing the road path). Decoding it gives us actual coordinates we
    # can sample at intervals to search for nearby places — the Directions API
    # itself has no concept of "places along the way", so we build that here.
    path = googlemaps.convert.decode_polyline(routes[0]["overview_polyline"]["points"])

    num_stops = max(1, int(total_km / interval_km))
    sample_indices = [int(i * (len(path) - 1) / (num_stops + 1)) for i in range(1, num_stops + 1)]

    seen = set()
    lines = []
    for idx in sample_indices:
        point = path[idx]
        nearby = gmaps.places_nearby(
            location=(point["lat"], point["lng"]), radius=5000, type=place_type
        )
        for place in nearby.get("results", [])[:2]:
            name = place.get("name")
            if name in seen:
                continue
            seen.add(name)
            rating = place.get("rating", "N/A")
            lines.append(f"{name} (rating: {rating})")

    if not lines:
        return f"No {place_type} found along the route."
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
