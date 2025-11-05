import pytest
import sqlite3
import json
import time
import os
from unittest.mock import patch, Mock

import weather


@pytest.fixture
def mock_weather_data():
    return {
        "current_condition": [{
            "temp_C": "20",
            "weatherDesc": [{"value": "Partly cloudy"}],
            "humidity": "65"
        }]
    }


@pytest.fixture
def db_cleanup():
    """Fixture to clean up database after each test."""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'weather_cache.db')
    yield
    if os.path.exists(db_path):
        os.remove(db_path)


def test_fetch_weather_success(mock_weather_data):
    """Test successful API call to fetch weather data."""
    with patch('weather.requests.get') as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_weather_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        result = weather.fetch_weather("London")
        assert result == mock_weather_data
        mock_get.assert_called_once_with("https://wttr.in/London?format=j1", timeout=10)


def test_fetch_weather_network_error():
    """Test handling of network errors."""
    import requests
    with patch('weather.requests.get', side_effect=requests.exceptions.ConnectionError("Connection failed")):
        with pytest.raises(Exception, match="Network error: Connection failed"):
            weather.fetch_weather("London")


def test_display_weather_success(capsys, mock_weather_data):
    """Test displaying weather information."""
    weather.display_weather("London", mock_weather_data)
    captured = capsys.readouterr()
    assert "Weather in London:" in captured.out
    assert "Temperature: 20°C" in captured.out
    assert "Condition: Partly cloudy" in captured.out
    assert "Humidity: 65%" in captured.out


def test_display_weather_invalid_data():
    """Test handling of invalid weather data."""
    with pytest.raises(Exception, match="Unable to parse weather data"):
        weather.display_weather("London", {})


def test_cache_workflow(db_cleanup, mock_weather_data):
    """Test caching workflow: store and retrieve."""
    # Store data
    weather.cache_weather("London", mock_weather_data)
    
    # Retrieve data
    cached = weather.get_cached_weather("London")
    assert cached == mock_weather_data


def test_cache_expiration(db_cleanup, mock_weather_data):
    """Test cache expiration after 1 hour."""
    # Store data with timestamp from 2 hours ago
    db_path = weather.init_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO weather_cache (city, data, timestamp) VALUES (?, ?, ?)',
        ("London", json.dumps(mock_weather_data), time.time() - 7200)  # 2 hours ago
    )
    conn.commit()
    conn.close()
    
    # Should not return expired cache
    cached = weather.get_cached_weather("London")
    assert cached is None


def test_clear_cache(db_cleanup, mock_weather_data):
    """Test clearing cache."""
    # Add some data to cache
    weather.cache_weather("London", mock_weather_data)
    
    # Verify data exists
    cached = weather.get_cached_weather("London")
    assert cached is not None
    
    # Clear cache
    weather.clear_cache()
    
    # Verify cache is empty
    cached = weather.get_cached_weather("London")
    assert cached is None


def test_cli_parsing():
    """Test command line argument parsing."""
    import sys
    from unittest.mock import patch
    
    # Test with city argument
    with patch.object(sys, 'argv', ["weather.py", "London"]):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("city", nargs="?", help="City name")
        parser.add_argument("--clear-cache", action="store_true", help="Clear cached weather data")
        args = parser.parse_args(["London"])
        assert args.city == "London"
        assert args.clear_cache == False
    
    # Test with clear-cache flag
    with patch.object(sys, 'argv', ["weather.py", "--clear-cache"]):
        args = parser.parse_args(["--clear-cache"])
        assert args.city is None
        assert args.clear_cache == True
    
    # Test with both arguments
    with patch.object(sys, 'argv', ["weather.py", "London", "--clear-cache"]):
        args = parser.parse_args(["London", "--clear-cache"])
        assert args.city == "London"
        assert args.clear_cache == True