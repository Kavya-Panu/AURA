"""Tests for AURA's live weather service and BrainManager routing."""
import unittest

from brain import BrainManager
from brain.weather_service import FORECAST_URL, GEOCODING_URL, WeatherService
from core.event_bus import EventBus


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestWeatherService(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_get(url, *, params, timeout):
            self.calls.append((url, params, timeout))
            if url == GEOCODING_URL:
                return _Response({
                    "results": [{
                        "name": "Liverpool",
                        "latitude": 53.41058,
                        "longitude": -2.97794,
                    }]
                })
            if url == FORECAST_URL:
                return _Response({
                    "current": {
                        "temperature_2m": 21.7,
                        "apparent_temperature": 20.6,
                        "relative_humidity_2m": 54,
                        "precipitation": 0,
                        "rain": 0,
                        "weather_code": 3,
                        "wind_speed_10m": 13.7,
                        "wind_gusts_10m": 27,
                    }
                })
            raise AssertionError(url)

        self.service = WeatherService(http_get=fake_get)

    def test_detects_current_weather_question(self):
        self.assertTrue(self.service.is_current_weather_question(
            "What's the weather right now?"))
        self.assertTrue(self.service.is_current_weather_question(
            "Is it raining in Manchester?"))
        self.assertFalse(self.service.is_current_weather_question(
            "What will the weather be tomorrow?"))

    def test_default_location_and_spoken_answer(self):
        answer = self.service.current("What's the weather right now?")
        self.assertTrue(answer.success)
        self.assertEqual(answer.location, "Liverpool")
        self.assertEqual(
            answer.text,
            "It is overcast and 21.7 degrees Celsius in Liverpool right now.",
        )
        self.assertIn("21.7 degrees Celsius", answer.text)
        self.assertEqual(self.calls[0][1]["countryCode"], "GB")

    def test_explicit_location_does_not_force_default_country(self):
        answer = self.service.current("What is the weather in Liverpool now?")
        self.assertTrue(answer.success)
        self.assertNotIn("countryCode", self.calls[0][1])

    def test_how_hot_is_city_extracts_city_and_is_short(self):
        answer = self.service.current("How hot is London?")
        self.assertTrue(answer.success)
        self.assertEqual(self.calls[0][1]["name"], "London")
        self.assertEqual(
            answer.text,
            "It is 21.7 degrees Celsius in Liverpool, feeling like 20.6.",
        )

    def test_question_specific_short_answers(self):
        rain = self.service.current("Is it raining?")
        self.assertEqual(rain.text, "No, it is not raining in Liverpool right now.")

        wind = self.service.current("Is it windy outside?")
        self.assertEqual(
            wind.text,
            "It is a little breezy in Liverpool: 13.7 kilometres per hour, "
            "with gusts up to 27.",
        )

    def test_clipped_location_fragment(self):
        self.assertTrue(self.service.is_location_fragment("of Manchester."))
        answer = self.service.current("of Manchester.")
        self.assertTrue(answer.success)
        self.assertEqual(self.calls[0][1]["name"], "Manchester")

    def test_weather_is_cached(self):
        self.service.current("weather right now")
        self.service.current("weather right now")
        self.assertEqual(len(self.calls), 2)

    def test_brain_routes_weather_without_language_model(self):
        brain = BrainManager(EventBus(), weather_service=self.service)
        result = brain.ask("What's the weather right now?", mode="ASSISTANT")
        self.assertTrue(result.success)
        self.assertEqual(result.provider, "open-meteo")
        self.assertEqual(result.metadata["task"], "weather")
        self.assertTrue(result.metadata["live"])


if __name__ == "__main__":
    unittest.main()
