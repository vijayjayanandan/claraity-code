#!/usr/bin/env python3
"""
Command-line weather tool that fetches data from wttr.in with caching.
"""

import argparse
import requests
import sqlite3
import json
import time
import sys
import os


def init_db():
    """Initialize the SQLite database for caching."""
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'weather_cache.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS weather_cache (
            city TEXT PRIMARY KEY,
            data TEXT,
            timestamp REAL
        )
    ''')
    conn.commit()
    conn.close()
    return db_path


def get_cached_weather(city):
    """Retrieve weather data from cache if available and not expired."""
    db_path = init_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('SELECT data, timestamp FROM weather_cache WHERE city = ?', (city,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        data, timestamp = result
        # Check if cache is less than 1 hour old
        if time.time() - timestamp < 3600:
            return json.loads(data)
    return None


def cache_weather(city, data):
    """Cache weather data in SQLite database."""
    db_path = init_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Delete existing entry if exists
    cursor.execute('DELETE FROM weather_cache WHERE city = ?', (city,))
    
    # Insert new data
    cursor.execute(
        'INSERT INTO weather_cache (city, data, timestamp) VALUES (?, ?, ?)',
        (city, json.dumps(data), time.time())
    )
    
    conn.commit()
    conn.close()


def fetch_weather(city):
    """Fetch weather data from wttr.in API."""
    try:
        url = f"https://wttr.in/{city}?format=j1"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Network error: {e}")
    except json.JSONDecodeError:
        raise Exception("Invalid response from weather service")


def display_weather(city, weather_data):
    """Display formatted weather information."""
    try:
        current = weather_data['current_condition'][0]
        temp = current['temp_C']
        condition = current['weatherDesc'][0]['value']
        humidity = current['humidity']
        
        print(f"Weather in {city}:")
        print(f"Temperature: {temp}°C")
        print(f"Condition: {condition}")
        print(f"Humidity: {humidity}%")
    except (KeyError, IndexError):
        raise Exception("Unable to parse weather data")


def clear_cache():
    """Clear all cached weather data."""
    db_path = init_db()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM weather_cache')
    conn.commit()
    conn.close()
    print("Cache cleared successfully.")


def main():
    parser = argparse.ArgumentParser(description="Get weather information for a city")
    parser.add_argument("city", nargs="?", help="City name")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cached weather data")
    
    args = parser.parse_args()
    
    if args.clear_cache:
        clear_cache()
        if not args.city:
            return
    
    if not args.city:
        parser.print_help()
        return
    
    try:
        # Try to get cached data first
        cached_data = get_cached_weather(args.city)
        if cached_data:
            print("Using cached data...")
            display_weather(args.city, cached_data)
            return
        
        # Fetch fresh data if not cached or expired
        print("Fetching fresh data...")
        weather_data = fetch_weather(args.city)
        cache_weather(args.city, weather_data)
        display_weather(args.city, weather_data)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()