"""
15_build_website.py
===================
Assemble the Website/ directory: copy data files, copy interactive Folium map,
and verify the static site structure is complete.

The HTML/CSS/JS files are maintained directly in the Website/ directory.
This script copies the Folium interactive map and verifies all required files.
"""

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEBSITE_DIR = PROJECT_ROOT / "Website"
DATA_DIR = WEBSITE_DIR / "data"
INTERACTIVE_DIR = WEBSITE_DIR / "interactive"
OUTPUTS_DIR = PROJECT_ROOT / "Outputs"

# Ensure directories exist
for d in [WEBSITE_DIR, DATA_DIR, INTERACTIVE_DIR,
          WEBSITE_DIR / "css", WEBSITE_DIR / "js"]:
    d.mkdir(parents=True, exist_ok=True)

# --- Copy interactive Folium map for Section 6 ---
print("Copying interactive Folium map...")
folium_src = OUTPUTS_DIR / "la_transit_density_hex_blocks_small.html"
folium_dst = INTERACTIVE_DIR / "la_transit_hex.html"

if folium_src.exists():
    shutil.copy2(folium_src, folium_dst)
    size_mb = folium_dst.stat().st_size / 1e6
    print(f"  → {folium_dst} ({size_mb:.1f} MB)")
else:
    print(f"  WARNING: {folium_src} not found. Section 6 iframe will not work.")
    print("  Run script 04b first to generate the interactive map.")

# --- Verify data files ---
print("\nVerifying data files...")
expected_data = [
    "blocks_binned.topojson",
    "hex_deserts.geojson",
    "corridor_profiles.json",
    "coverage_stats.json",
    "counterfactual_stations.geojson",
    "counterfactual_stats.json",
    "county_boundary.geojson",
]

missing = []
for name in expected_data:
    p = DATA_DIR / name
    if p.exists():
        print(f"  ✓ {name} ({p.stat().st_size / 1e3:.0f} KB)")
    else:
        print(f"  ✗ {name} MISSING")
        missing.append(name)

if missing:
    print(f"\n  WARNING: {len(missing)} data file(s) missing. Run script 09 first.")

# --- Verify website files ---
print("\nVerifying website files...")
expected_files = [
    "index.html",
    "css/style.css",
    "js/visualizations.js",
    "js/scroll.js",
]

for name in expected_files:
    p = WEBSITE_DIR / name
    if p.exists():
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} MISSING")

print(f"\nWebsite directory: {WEBSITE_DIR}")
print("To preview: cd Website && python -m http.server 8000")
print("Then open: http://localhost:8000")
