"""
01b_process_census_blocks.py
============================
Fetch 2020 Decennial Census block population for LA County,
join to TIGER/Line block boundaries, compute population density,
and save to Data/la_blocks_density.geojson.

Run from project root:
    python Scripting/01b_process_census_blocks.py
"""

import os
import sys
import zipfile
from pathlib import Path
import pandas as pd
import geopandas as gpd
from dotenv import load_dotenv
import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
OUTPUT_PATH = DATA_DIR / "la_blocks_density.geojson"
BLOCKS_DIR = DATA_DIR / "census_blocks"
BLOCKS_SHP = BLOCKS_DIR / "tl_2025_06_tabblock20.shp"
BLOCKS_ZIP = DATA_DIR / "tl_2025_06_tabblock20.zip"

# ---------------------------------------------------------------------------
# Load Census API key
# ---------------------------------------------------------------------------
load_dotenv(PROJECT_ROOT / ".env")
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")
if not CENSUS_API_KEY:
    sys.exit("ERROR: CENSUS_API_KEY not found in .env")

# ---------------------------------------------------------------------------
# Download TIGER/Line block shapefile
# ---------------------------------------------------------------------------
BLOCKS_DIR.mkdir(parents=True, exist_ok=True)

if not BLOCKS_SHP.exists():
    if not BLOCKS_ZIP.exists():
        sys.exit(
            f"ERROR: Block shapefile zip not found at {BLOCKS_ZIP}\n"
            "Download from https://www2.census.gov/geo/tiger/TIGER2025/TABBLOCK20/tl_2025_06_tabblock20.zip"
        )
    print(f"  Unzipping {BLOCKS_ZIP} to {BLOCKS_DIR} ...")
    with zipfile.ZipFile(BLOCKS_ZIP, "r") as zf:
        zf.extractall(BLOCKS_DIR)
    print("  Done.")
else:
    print(f"Block shapefile already exists at {BLOCKS_SHP}")

# ---------------------------------------------------------------------------
# Load block boundaries
# ---------------------------------------------------------------------------
print(f"Loading block boundaries from {BLOCKS_SHP} ...")
gdf = gpd.read_file(BLOCKS_SHP)
print(f"  Loaded {len(gdf)} California blocks (CRS: {gdf.crs})")

# Filter to LA County (COUNTYFP20 == "037")
gdf = gdf[gdf["COUNTYFP20"] == "037"].copy()
print(f"  Filtered to LA County: {len(gdf)} blocks")

# ---------------------------------------------------------------------------
# Fetch 2020 Decennial Census block population
# ---------------------------------------------------------------------------
print("Fetching 2020 Decennial Census block population for LA County...")

VARIABLE = "P1_001N"  # Total population

url = (
    "https://api.census.gov/data/2020/dec/pl"
    f"?get={VARIABLE}"
    "&for=block:*"
    "&in=state:06%20county:037"
    f"&key={CENSUS_API_KEY}"
)

resp = requests.get(url, timeout=120)
resp.raise_for_status()
data = resp.json()

df_pop = pd.DataFrame(data[1:], columns=data[0])
print(f"  Downloaded {len(df_pop)} blocks from Census API")

df_pop = df_pop.rename(columns={VARIABLE: "population"})
df_pop["population"] = pd.to_numeric(df_pop["population"], errors="coerce")

# Build GEOID20 from state+county+tract+block (15 chars)
df_pop["GEOID20"] = df_pop["state"] + df_pop["county"] + df_pop["tract"] + df_pop["block"]

print(f"  Null population values: {df_pop['population'].isna().sum()}")

# ---------------------------------------------------------------------------
# Compute area in sq km (reproject to CA Albers EPSG:3310)
# ---------------------------------------------------------------------------
print("Computing block area in sq km (EPSG:3310) ...")
gdf_proj = gdf.to_crs("EPSG:3310")
gdf["area_sqkm"] = gdf_proj.geometry.area / 1_000_000  # m² → km²

# ---------------------------------------------------------------------------
# Merge population onto geometries
# ---------------------------------------------------------------------------
print("Merging population data onto geometries...")
gdf = gdf.merge(
    df_pop[["GEOID20", "population"]],
    on="GEOID20",
    how="left",
)

missing = gdf["population"].isna().sum()
if missing > 0:
    print(f"  WARNING: {missing} blocks have no population data (will be excluded from density calc)")

# ---------------------------------------------------------------------------
# Compute density
# ---------------------------------------------------------------------------
gdf["density"] = gdf["population"] / gdf["area_sqkm"]

# Keep relevant columns (match tract schema)
cols_keep = ["GEOID20", "population", "area_sqkm", "density", "geometry"]
gdf = gdf[cols_keep].copy()

# Ensure WGS84 for output
gdf = gdf.to_crs("EPSG:4326")

# ---------------------------------------------------------------------------
# Save output
# ---------------------------------------------------------------------------
print(f"Saving to {OUTPUT_PATH} ...")
gdf.to_file(OUTPUT_PATH, driver="GeoJSON")

print(f"\nDone. {len(gdf)} blocks saved.")
print(f"  Total population: {gdf['population'].sum():,.0f}")
print(f"  Density range: {gdf['density'].min():.1f} – {gdf['density'].max():.1f} persons/km²")
print(f"  Null density values: {gdf['density'].isna().sum()}")
