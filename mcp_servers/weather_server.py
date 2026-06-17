"""
weather_server.py — a real MCP (Model Context Protocol) server.
================================================================

This is NOT an A2A agent. It's an MCP **tool server**: it exposes a single
tool, `get_weather`, that fetches a *real* forecast from the free, key-less
Open-Meteo API. The Weather Advisor A2A agent connects to this server as an
MCP **client** and calls the tool.

That's the A2A-vs-MCP story made concrete:
    orchestrator --(A2A)--> Weather Advisor agent --(MCP)--> THIS tool --> Open-Meteo

We serve it over MCP's "streamable-http" transport so it's a normal service on
a port (8200) that the launcher can start and you can see in the diagram.

    python -m mcp_servers.weather_server      # serves MCP at http://127.0.0.1:8200/mcp
"""
from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

MCP_PORT = 8200

mcp = FastMCP("weather-tools", host="127.0.0.1", port=MCP_PORT)

# WMO weather interpretation codes -> short human descriptions.
WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog", 51: "light drizzle", 53: "drizzle",
    55: "dense drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "rain showers", 81: "rain showers",
    82: "violent rain showers", 85: "snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


@mcp.tool()
async def get_weather(location: str, days: int = 5) -> str:
    """Get a real short-term weather forecast for a place name.

    Args:
        location: a city/place name, e.g. "Kyoto" or "Lisbon".
        days: how many forecast days to return (1-16).

    Returns a short, human-readable multi-day forecast (temperatures in °C,
    precipitation in mm, sky conditions). Data source: Open-Meteo.
    """
    days = max(1, min(int(days), 16))
    async with httpx.AsyncClient(timeout=15) as client:
        # 1) turn the place name into coordinates (geocoding)
        geo = (await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"},
        )).json()
        results = geo.get("results") or []
        if not results:
            return f"No location found matching '{location}'."
        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        nice_name = ", ".join(filter(None, [place.get("name"), place.get("country")]))

        # 2) fetch the daily forecast for those coordinates
        fc = (await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "forecast_days": days, "timezone": "auto",
            },
        )).json()

    daily = fc.get("daily", {})
    times = daily.get("time", [])
    lines = [f"Live forecast for {nice_name} (next {len(times)} days):"]
    for i, day in enumerate(times):
        tmin = daily["temperature_2m_min"][i]
        tmax = daily["temperature_2m_max"][i]
        precip = daily["precipitation_sum"][i]
        sky = WMO.get(daily["weather_code"][i], "unknown")
        lines.append(f"- {day}: {round(tmin)}–{round(tmax)}°C, {sky}, precip {precip}mm")
    return "\n".join(lines)


if __name__ == "__main__":
    # streamable-http transport -> available at http://127.0.0.1:8200/mcp
    mcp.run(transport="streamable-http")
