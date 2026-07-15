import logging

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.WARNING)  # silence MCP's per-request INFO logs

mcp = FastMCP("Weather")

# WMO weather codes -> human-readable description (Open-Meteo returns a numeric code, not text)
WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


@mcp.tool()
async def get_weather(location: str) -> str:
    """Get the current real-time weather for a location (city/place name)."""
    async with httpx.AsyncClient() as client:
        # Step 1: turn "San Francisco" into lat/lon — the forecast API needs coordinates, not names.
        geo_resp = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1},
        )
        geo_results = geo_resp.json().get("results")
        if not geo_results:
            return f"Could not find a location matching '{location}'."

        place = geo_results[0]
        lat, lon = place["latitude"], place["longitude"]

        # Step 2: fetch current weather for those coordinates.
        weather_resp = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": lat, "longitude": lon, "current_weather": "true"},
        )
        current = weather_resp.json().get("current_weather")
        if not current:
            return f"No current weather data available for {location}."

    description = WEATHER_CODES.get(current["weathercode"], "Unknown conditions")
    place_name = f"{place['name']}, {place.get('country', '')}".strip(", ")
    return (
        f"{place_name}: {description}, {current['temperature']}°C, "
        f"wind {current['windspeed']} km/h"
    )


if __name__ == "__main__":
    mcp.run(transport="sse")
