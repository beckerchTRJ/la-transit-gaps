"""
01_process_census.py
====================
Fetch ACS 5-Year population data for LA County census tracts,
join to TIGER/Line tract boundaries, compute population density,
and save to Data/la_tracts_density.geojson.

Run from project root:
    python Scripting/01_process_census.py
"""

import os
import sys
from pathlib import Path
import pandas as pd
import geopandas as gpd
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
OUTPUT_PATH = DATA_DIR / "la_tracts_density.geojson"
TRACTS_SHP = DATA_DIR / "census_tracts" / "tl_2025_06_tract.shp"

# ---------------------------------------------------------------------------
# Load Census API key
# ---------------------------------------------------------------------------
load_dotenv(PROJECT_ROOT / ".env")
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")
if not CENSUS_API_KEY:
    sys.exit("ERROR: CENSUS_API_KEY not found in .env")

# ---------------------------------------------------------------------------
# Fetch ACS data via Census API (requests)
# ---------------------------------------------------------------------------
print("Fetching ACS 5-Year population data for LA County tracts...")

import requests

VARIABLE = "B01003_001E"  # Total population

url = (
    "https://api.census.gov/data/2023/acs/acs5"
    f"?get=NAME,{VARIABLE}"
    "&for=tract:*"
    "&in=state:06%20county:037"
    f"&key={CENSUS_API_KEY}"
)

resp = requests.get(url, timeout=60)
resp.raise_for_status()
data = resp.json()

# First row is header, rest are data rows
df_pop = pd.DataFrame(data[1:], columns=data[0])

print(f"  Downloaded {len(df_pop)} tracts from Census API")

# Rename columns for clarity
df_pop = df_pop.rename(columns={VARIABLE: "population", "NAME": "tract_name"})
df_pop["population"] = pd.to_numeric(df_pop["population"], errors="coerce")

# Build GEOID for merging (state + county + tract, 11 chars)
df_pop["GEOID"] = df_pop["state"] + df_pop["county"] + df_pop["tract"]

print(f"  Null population values: {df_pop['population'].isna().sum()}")

# ---------------------------------------------------------------------------
# Load census tract boundaries
# ---------------------------------------------------------------------------
print(f"Loading tract boundaries from {TRACTS_SHP} ...")
if not TRACTS_SHP.exists():
    sys.exit(f"ERROR: Shapefile not found at {TRACTS_SHP}")

gdf = gpd.read_file(TRACTS_SHP)
print(f"  Loaded {len(gdf)} California tracts (CRS: {gdf.crs})")

# Filter to LA County (COUNTYFP == "037")
gdf = gdf[gdf["COUNTYFP"] == "037"].copy()
print(f"  Filtered to LA County: {len(gdf)} tracts")

# ---------------------------------------------------------------------------
# Compute area in sq km (reproject to CA Albers EPSG:3310)
# ---------------------------------------------------------------------------
print("Computing tract area in sq km (EPSG:3310) ...")
gdf_proj = gdf.to_crs("EPSG:3310")
gdf["area_sqkm"] = gdf_proj.geometry.area / 1_000_000  # m² → km²

# ---------------------------------------------------------------------------
# Merge population onto geometries
# ---------------------------------------------------------------------------
print("Merging population data onto geometries...")
gdf = gdf.merge(
    df_pop[["GEOID", "tract_name", "population"]],
    on="GEOID",
    how="left",
)
# Use the Census tract name as NAME (replace shapefile NAME column)
gdf["NAME"] = gdf["tract_name"]
gdf = gdf.drop(columns=["tract_name"])

missing = gdf["population"].isna().sum()
if missing > 0:
    print(f"  WARNING: {missing} tracts have no population data (will be excluded from density calc)")

# ---------------------------------------------------------------------------
# Compute density
# ---------------------------------------------------------------------------
gdf["density"] = gdf["population"] / gdf["area_sqkm"]

# Keep relevant columns
cols_keep = ["GEOID", "NAME", "population", "area_sqkm", "density", "geometry"]
gdf = gdf[cols_keep].copy()

# Ensure WGS84 for output
gdf = gdf.to_crs("EPSG:4326")

# ---------------------------------------------------------------------------
# Save output
# ---------------------------------------------------------------------------
print(f"Saving to {OUTPUT_PATH} ...")
gdf.to_file(OUTPUT_PATH, driver="GeoJSON")

print(f"\nDone. {len(gdf)} tracts saved.")
print(f"  Density range: {gdf['density'].min():.1f} – {gdf['density'].max():.1f} persons/km²")
print(f"  Null density values: {gdf['density'].isna().sum()}")
