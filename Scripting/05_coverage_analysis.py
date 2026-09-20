"""
05_coverage_analysis.py
=======================
Compute walking-distance transit coverage for LA County:
  - ¼ mile (1,320 ft / ~402 m) buffer around bus stops (FTA/TCRP standard ~5-min walk)
  - ½ mile (2,640 ft / ~805 m) buffer around rail stations (~10-min walk)

Outputs:
  - Data/coverage_quarter_mi_bus.geojson   (dissolved bus buffer polygon)
  - Data/coverage_half_mi_rail.geojson     (dissolved rail buffer polygon)
  - Data/coverage_stats.json               (population coverage statistics)
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"

STOPS_PATH = DATA_DIR / "transit_stops.geojson"
BLOCKS_PATH = DATA_DIR / "la_blocks_density.geojson"

for p in [STOPS_PATH, BLOCKS_PATH]:
    if not p.exists():
        sys.exit(f"ERROR: Required file not found: {p}")

# Buffer distances in meters (working in EPSG:3310)
QUARTER_MI_M = 402.336  # 1,320 ft
HALF_MI_M = 804.672     # 2,640 ft

print("Loading data...")
stops = gpd.read_file(STOPS_PATH).to_crs("EPSG:3310")
blocks = gpd.read_file(BLOCKS_PATH).to_crs("EPSG:3310")

# Separate bus and rail stops
bus_stops = stops[stops["route_category"].isin(["metro_bus", "local_bus"])].copy()
rail_stops = stops[stops["route_category"].isin(["metro_rail", "commuter_rail"])].copy()

print(f"  Bus stops: {len(bus_stops)}, Rail stations: {len(rail_stops)}")

# --- Bus coverage (¼ mile) ---
print("Computing ¼-mile bus buffer...")
bus_buffer = bus_stops.geometry.buffer(QUARTER_MI_M)
bus_coverage = gpd.GeoDataFrame(geometry=[bus_buffer.union_all()], crs="EPSG:3310")

# --- Rail coverage (½ mile) ---
print("Computing ½-mile rail buffer...")
rail_buffer = rail_stops.geometry.buffer(HALF_MI_M)
rail_coverage = gpd.GeoDataFrame(geometry=[rail_buffer.union_all()], crs="EPSG:3310")

# --- Population coverage via spatial join ---
print("Computing population coverage...")

# Block centroids for point-in-polygon test
blocks["centroid"] = blocks.geometry.centroid
block_points = blocks.set_geometry("centroid")

total_pop = int(blocks["population"].sum())

# Bus coverage
bus_covered = gpd.sjoin(block_points, bus_coverage, how="inner", predicate="within")
bus_pop = int(bus_covered["population"].sum())

# Rail coverage
rail_covered = gpd.sjoin(block_points, rail_coverage, how="inner", predicate="within")
rail_pop = int(rail_covered["population"].sum())

bus_pct = round(100 * bus_pop / total_pop, 1)
rail_pct = round(100 * rail_pop / total_pop, 1)

stats = {
    "total_population": total_pop,
    "bus_quarter_mi": {
        "population_covered": bus_pop,
        "percent_covered": bus_pct,
        "buffer_distance_mi": 0.25,
        "buffer_distance_m": round(QUARTER_MI_M),
    },
    "rail_half_mi": {
        "population_covered": rail_pop,
        "percent_covered": rail_pct,
        "buffer_distance_mi": 0.5,
        "buffer_distance_m": round(HALF_MI_M),
    },
}

print(f"\n  Total population: {total_pop:,}")
print(f"  Bus (¼ mi): {bus_pop:,} ({bus_pct}%)")
print(f"  Rail (½ mi): {rail_pop:,} ({rail_pct}%)")

# --- Save outputs ---
print("\nSaving outputs...")
bus_coverage.to_crs("EPSG:4326").to_file(DATA_DIR / "coverage_quarter_mi_bus.geojson", driver="GeoJSON")
rail_coverage.to_crs("EPSG:4326").to_file(DATA_DIR / "coverage_half_mi_rail.geojson", driver="GeoJSON")

with open(DATA_DIR / "coverage_stats.json", "w") as f:
    json.dump(stats, f, indent=2)

print("Done.")
