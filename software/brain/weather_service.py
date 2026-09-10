"""Live current-weather lookup for AURA using the Open-Meteo APIs.

This module deliberately owns only weather intent detection, location lookup,
and concise spoken-answer formatting.  It has no knowledge of the display,
speech hardware, or the language-model provider.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True)
class WeatherAnswer:
    """A ready-to-speak weather answer."""

    text: str
    location: str
    success: bool = True
    error: str = ""


class WeatherService:
    """Fetches live current conditions and creates a short spoken response."""

    _FUTURE_RE = re.compile(
        r"\b(tomorrow|next\s+week|weekend|next\s+month|forecast|later\s+this\s+week)\b",
        re.IGNORECASE,
    )
    _WEATHER_RE = re.compile(
        r"\b(weather|temperature|raining|rainy|rain|snowing|snowy|sunny|"
        r"windy|wind|cold|hot|warm|conditions?)\b",
        re.IGNORECASE,
    )
    _LOCATION_RE = re.compile(
        r"\b(?:in|for|at|of)\s+([A-Za-z][A-Za-z .,'-]{0,70}?)(?="
        r"\s+(?:right\s+now|now|currently|today)\b|[?!.]*$)",
        re.IGNORECASE,
    )
    _HOW_LOCATION_RE = re.compile(
        r"\bhow\s+(?:hot|cold|warm|windy)\s+is(?:\s+it)?\s+"
        r"(?:in\s+)?([A-Za-z][A-Za-z .,'-]{0,70}?)(?=[?!.]*$)",
        re.IGNORECASE,
    )
    _LOCATION_FRAGMENT_RE = re.compile(
        r"^(?:in|for|at|of|is)\s+[A-Za-z][A-Za-z .,'-]{1,70}[?!.]*$",
        re.IGNORECASE,
    )
    _TRAILING_TIME_RE = re.compile(
        r"\s+(?:right\s+now|now|currently|today)\s*$", re.IGNORECASE
    )

    def __init__(
        self,
        default_location: str = "Liverpool",
        default_country_code: str = "GB",
        *,
        timeout_s: float = 6.0,
        cache_seconds: float = 120.0,
        http_get: Callable[..., Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.default_location = default_location.strip() or "Liverpool"
        self.default_country_code = default_country_code.strip().upper() or "GB"
        self._timeout_s = timeout_s
        self._cache_seconds = cache_seconds
        self._get = http_get or httpx.get
        self._clock = clock
        self._lock = threading.RLock()
        self._location_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._weather_cache: dict[str, tuple[float, WeatherAnswer]] = {}

    def is_current_weather_question(self, question: str) -> bool:
        """Return True for current-condition questions, not future forecasts."""
        text = " ".join(question.strip().split())
        if not text or self._FUTURE_RE.search(text):
            return False
        return self._WEATHER_RE.search(text) is not None

    def is_location_fragment(self, question: str) -> bool:
        """Recognise a clipped follow-up such as ``of Manchester``."""
        text = question.strip()
        return (
            self._WEATHER_RE.search(text) is None
            and self._LOCATION_FRAGMENT_RE.fullmatch(text) is not None
        )

    def current(self, question: str) -> WeatherAnswer:
        """Look up the requested location and return a concise spoken answer."""
        requested, country_code, used_default = self._extract_location(question)
        cache_key = (
            f"{requested.casefold()}|{country_code or ''}|{self._answer_intent(question)}"
        )

        with self._lock:
            cached = self._weather_cache.get(cache_key)
            if cached and self._clock() - cached[0] < self._cache_seconds:
                return cached[1]

        try:
            place = self._geocode(requested, country_code if used_default else country_code)
            answer = self._fetch_current(place, question)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return WeatherAnswer(
                text=(
                    f"Sorry, I could not get live weather for {requested} right now."
                ),
                location=requested,
                success=False,
                error=str(exc),
            )

        with self._lock:
            self._weather_cache[cache_key] = (self._clock(), answer)
        return answer

    def _extract_location(self, question: str) -> tuple[str, str | None, bool]:
        text = " ".join(question.strip().split())
        if self.is_location_fragment(text):
            requested = re.sub(
                r"^(?:in|for|at|of|is)\s+", "", text, flags=re.IGNORECASE
            ).strip(" ,?.!")
            if self._is_non_location(requested):
                return self.default_location, self.default_country_code, True
            return requested, None, False

        match = self._LOCATION_RE.search(text) or self._HOW_LOCATION_RE.search(text)
        if not match:
            return self.default_location, self.default_country_code, True

        requested = self._TRAILING_TIME_RE.sub("", match.group(1)).strip(" ,?.!")
        if not requested or self._is_non_location(requested):
            return self.default_location, self.default_country_code, True

        country_code: str | None = None
        if "," in requested:
            city, country = (part.strip() for part in requested.rsplit(",", 1))
            aliases = {
                "uk": "GB",
                "gb": "GB",
                "united kingdom": "GB",
                "usa": "US",
                "us": "US",
                "united states": "US",
            }
            country_code = aliases.get(country.casefold())
            if country_code:
                requested = city
        return requested, country_code, False

    @staticmethod
    def _is_non_location(value: str) -> bool:
        text = value.casefold().strip()
        return (
            text in {"it", "outside", "here", "there", "right now", "now"}
            or text.startswith("it ")
        )

    def _geocode(self, name: str, country_code: str | None) -> dict[str, Any]:
        key = f"{name.casefold()}|{country_code or ''}"
        with self._lock:
            cached = self._location_cache.get(key)
            if cached:
                return cached[1]

        params: dict[str, Any] = {
            "name": name,
            "count": 5,
            "language": "en",
            "format": "json",
        }
        if country_code:
            params["countryCode"] = country_code

        response = self._get(GEOCODING_URL, params=params, timeout=self._timeout_s)
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results:
            raise ValueError(f"location not found: {name}")
        place = results[0]
        if "latitude" not in place or "longitude" not in place:
            raise ValueError(f"location has no coordinates: {name}")
        with self._lock:
            self._location_cache[key] = (self._clock(), place)
        return place

    def _fetch_current(self, place: dict[str, Any], question: str) -> WeatherAnswer:
        params = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "precipitation,rain,weather_code,wind_speed_10m,wind_gusts_10m"
            ),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
            "timezone": "auto",
        }
        response = self._get(FORECAST_URL, params=params, timeout=self._timeout_s)
        response.raise_for_status()
        current = response.json()["current"]

        location = str(place.get("name") or self.default_location)
        condition = self._condition(int(current["weather_code"]))
        temperature = self._number(current["temperature_2m"])
        feels = self._number(current["apparent_temperature"])
        humidity = self._number(current["relative_humidity_2m"])
        wind = self._number(current["wind_speed_10m"])
        gusts = self._number(current.get("wind_gusts_10m", current["wind_speed_10m"]))
        rain = float(current.get("rain", current.get("precipitation", 0.0)) or 0.0)

        intent = self._answer_intent(question)
        if intent == "rain":
            wet_code = int(current["weather_code"]) in {
                51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99
            }
            text = (
                f"Yes, it is raining in {location} right now."
                if rain >= 0.1 or wet_code
                else f"No, it is not raining in {location} right now."
            )
        elif intent == "temperature":
            text = (
                f"It is {temperature} degrees Celsius in {location}, "
                f"feeling like {feels}."
            )
        elif intent == "wind":
            wind_value = float(current["wind_speed_10m"])
            description = (
                "calm" if wind_value < 6 else
                "a little breezy" if wind_value < 20 else
                "windy" if wind_value < 40 else
                "very windy"
            )
            text = (
                f"It is {description} in {location}: {wind} kilometres per hour, "
                f"with gusts up to {gusts}."
            )
        else:
            text = f"It is {condition} and {temperature} degrees Celsius in {location} right now."
        return WeatherAnswer(text=text, location=location)

    @staticmethod
    def _answer_intent(question: str) -> str:
        text = question.casefold()
        if re.search(r"\b(raining|rainy|rain)\b", text):
            return "rain"
        if re.search(r"\b(windy|wind)\b", text):
            return "wind"
        if re.search(r"\b(how\s+hot|how\s+cold|temperature|hot\s+outside|cold\s+outside)\b", text):
            return "temperature"
        return "general"

    @staticmethod
    def _number(value: Any) -> str:
        number = float(value)
        if abs(number - round(number)) < 0.05:
            return str(int(round(number)))
        return f"{number:.1f}"

    @staticmethod
    def _condition(code: int) -> str:
        if code == 0:
            return "clear"
        if code == 1:
            return "mainly clear"
        if code == 2:
            return "partly cloudy"
        if code == 3:
            return "overcast"
        if code in (45, 48):
            return "foggy"
        if code in (51, 53, 55):
            return "drizzly"
        if code in (56, 57):
            return "freezing drizzle"
        if code in (61, 63, 65):
            return "rainy"
        if code in (66, 67):
            return "freezing rain"
        if code in (71, 73, 75, 77):
            return "snowy"
        if code in (80, 81, 82):
            return "showery"
        if code in (85, 86):
            return "snow showers"
        if code in (95, 96, 99):
            return "thunderstorms"
        return "mixed conditions"
