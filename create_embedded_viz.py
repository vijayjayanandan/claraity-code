#!/usr/bin/env python3
"""Create clarity-viz.html with embedded data (no CORS issues)."""

import json
from pathlib import Path

# Read the data
with open('clarity-data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Read the HTML template
with open('clarity-viz.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Replace the fetch call with embedded data
old_code = """        // Load data
        async function loadData() {
            const response = await fetch('clarity-data.json');
            clarityData = await response.json();"""

new_code = f"""        // Load data
        async function loadData() {{
            // Data embedded directly (no CORS issues!)
            clarityData = {json.dumps(data, indent=12)};"""

html = html.replace(old_code, new_code)

# Write the new HTML file
with open('clarity-viz-embedded.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("✅ Created clarity-viz-embedded.html with embedded data")
print("📂 File size:", len(html) // 1024, "KB")
print("🚀 Open clarity-viz-embedded.html in your browser - no server needed!")
