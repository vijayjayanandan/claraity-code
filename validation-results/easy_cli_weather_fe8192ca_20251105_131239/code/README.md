# Weather CLI Tool

A simple command-line weather tool that fetches weather data from [wttr.in](https://wttr.in/) with built-in caching.

## Features

- Fetches current weather data for any city
- Caches results for 1 hour to reduce API calls
- Simple command-line interface
- Handles network errors gracefully
- Works without an API key

## Installation

1. Clone or download this repository
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Get weather for a city
```bash
python weather.py "San Francisco"
```

Output:
```
Fetching fresh data...
Weather in San Francisco:
Temperature: 18°C
Condition: Partly cloudy
Humidity: 65%
```

### Using cached data
```bash
python weather.py "San Francisco"
```

Output:
```
Using cached data...
Weather in San Francisco:
Temperature: 18°C
Condition: Partly cloudy
Humidity: 65%
```

### Clear cache
```bash
python weather.py "London" --clear-cache
```

Output:
```
Cache cleared successfully.
Fetching fresh data...
Weather in London:
Temperature: 12°C
Condition: Overcast
Humidity: 78%
```

### Help
```bash
python weather.py --help
```

## How Caching Works

The tool uses a local SQLite database (`weather_cache.db`) to store weather data. Each entry is cached for 1 hour (3600 seconds). When you request weather for a city:

1. The tool first checks if there's cached data for that city
2. If found and less than 1 hour old, it displays the cached data
3. Otherwise, it fetches fresh data from wttr.in, updates the cache, and displays the results

## Dependencies

- Python 3.x
- requests library

See `requirements.txt` for detailed version information.

## Testing

Run the tests with pytest:
```bash
pytest test_weather.py -v
```