"""
06_transit_desert_score.py
==========================
Compute per-hex transit access scores and density-quintile deficit.

Method:
  1. Build H3 res-8 hex grid with population density (reuse utils_hex)
  2. For each hex: compute route-deduplicated, frequency-weighted access score.
     For each nearby stop within 2 km, look up which routes serve it and
     how many weekday trips each route makes. Group by route, keep only the
     nearest stop per route, then sum:
       score += mode_factor × sqrt(trips_per_day) × exp(-d / λ)
     where λ = 400m for bus, 800m for rail; mode_factor = 1 for bus,
     3 for metro rail, 1.5 for commuter rail.
  3. Filter to populated hexes (>1000 persons/mi²)
  4. Assign density quintile (1–5) within populated set
  5. Deficit = percentile rank within stratum − 0.5
       negative = underserved for its density peer group
  6. Label hexes with LA Times neighborhood names

Outputs:
  - Data/hex_transit_deserts.geojson
"""

import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from shapely.strtree import STRtree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
sys.path.insert(0, str(PROJECT_ROOT / "Scripting"))
from utils_hex import build_hex_density

BLOCKS_PATH = DATA_DIR / "la_blocks_density.geojson"
STOPS_PATH = DATA_DIR / "transit_stops.geojson"
STOP_ROUTE_PATH = DATA_DIR / "stop_route_trips.csv"

for p in [BLOCKS_PATH, STOPS_PATH, STOP_ROUTE_PATH]:
    if not p.exists():
        sys.exit(f"ERROR: Required file not found: {p}")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
QUARTER_MI_M = 402.336
HALF_MI_M = 804.672
DENSITY_THRESHOLD = 1000        # persons/mi²
BUS_DECAY_M = 400.0             # bus distance decay constant (meters)
RAIL_DECAY_M = 800.0            # rail distance decay constant (meters)
RAIL_MODE_FACTOR = 3.0          # metro rail premium (speed, reliability, dedicated ROW)
BRT_MODE_FACTOR = 2.0           # BRT premium (dedicated ROW, stations, but less capacity/permanence than rail)
COMMUTER_RAIL_MODE_FACTOR = 1.5 # commuter rail (infrequent but enables long-distance trips)
BRT_ROUTE_IDS = {"metro_bus:901-13196", "metro_bus:910-13196"}  # G Line (901), J Line (910)
SEARCH_RADIUS_M = 2000.0        # outer search radius

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading data...")
blocks = gpd.read_file(BLOCKS_PATH).to_crs("EPSG:4326")
blocks_3310 = blocks.to_crs("EPSG:3310")
blocks["block_area_m2"] = blocks_3310.geometry.area

stops = gpd.read_file(STOPS_PATH).to_crs("EPSG:3310")
stop_route_trips = pd.read_csv(STOP_ROUTE_PATH)

# Build lookup: stop_id → [(route_id, trips_per_day), ...]
stop_route_map = defaultdict(list)
for _, row in stop_route_trips.iterrows():
    stop_route_map[row["stop_id"]].append((row["route_id"], int(row["trips_per_day"])))

# Identify rail routes (for mode factor and decay constant)
rail_categories = {"metro_rail", "commuter_rail"}
rail_stop_ids = set(stops[stops["route_category"].isin(rail_categories)]["stop_id"])

# Build a route → category mapping from stop_route_trips + stops
# Routes prefixed with feed name, so we map feed → category
feed_category = stops[["feed", "route_category"]].drop_duplicates().set_index("feed")["route_category"].to_dict()

def route_category(route_id):
    """Infer category from the feed prefix in the route_id."""
    feed = route_id.split(":")[0] if ":" in route_id else ""
    return feed_category.get(feed, "local_bus")

# Pre-classify routes
route_is_metro_rail = {}
route_is_brt = {}
route_is_commuter_rail = {}
for rid in stop_route_trips["route_id"].unique():
    cat = route_category(rid)
    route_is_metro_rail[rid] = (cat == "metro_rail")
    route_is_brt[rid] = (rid in BRT_ROUTE_IDS)
    route_is_commuter_rail[rid] = (cat == "commuter_rail")

print(f"  {len(stops)} stops, {len(stop_route_trips)} stop-route pairs, "
      f"{stop_route_trips['route_id'].nunique()} unique routes")

# ---------------------------------------------------------------------------
# Build hex grid
# ---------------------------------------------------------------------------
print("Building hex grid...")
hex_gdf = build_hex_density(blocks, resolution=8)

# ---------------------------------------------------------------------------
# Compute route-deduplicated, frequency-weighted access scores
# ---------------------------------------------------------------------------
print("Computing route-deduplicated, frequency-weighted access scores...")
hex_3310 = hex_gdf.to_crs("EPSG:3310")
hex_centroids = list(hex_3310.geometry.centroid)

# Single spatial index for all stops
all_stop_geoms = stops.geometry.values
all_stop_ids = stops["stop_id"].values
stop_tree = STRtree(all_stop_geoms)

# Also build separate trees for the raw count fields
bus_stops = stops[stops["route_category"].isin(["metro_bus", "local_bus"])]
rail_stops = stops[stops["route_category"].isin(["metro_rail", "commuter_rail"])]
bus_tree = STRtree(bus_stops.geometry.values)
rail_tree = STRtree(rail_stops.geometry.values)

access_scores = []
bus_counts = []
rail_counts = []

for i, centroid in enumerate(hex_centroids):
    if i % 1000 == 0 and i > 0:
        print(f"    {i}/{len(hex_centroids)} hexes...")

    buf = centroid.buffer(SEARCH_RADIUS_M)
    idxs = stop_tree.query(buf, predicate="intersects")

    # Collect (route_id → best contribution) across all nearby stops
    route_best = {}  # route_id → best (mode_factor * sqrt(trips) * decay)

    for idx in idxs:
        sid = all_stop_ids[idx]
        d = centroid.distance(all_stop_geoms[idx])

        routes = stop_route_map.get(sid, [])
        if not routes:
            continue

        for rid, trips in routes:
            if route_is_metro_rail.get(rid, False):
                decay = np.exp(-d / RAIL_DECAY_M)
                factor = RAIL_MODE_FACTOR
            elif route_is_brt.get(rid, False):
                decay = np.exp(-d / RAIL_DECAY_M)
                factor = BRT_MODE_FACTOR
            elif route_is_commuter_rail.get(rid, False):
                decay = np.exp(-d / RAIL_DECAY_M)
                factor = COMMUTER_RAIL_MODE_FACTOR
            else:
                decay = np.exp(-d / BUS_DECAY_M)
                factor = 1.0

            contribution = factor * np.sqrt(trips) * decay

            if rid not in route_best or contribution > route_best[rid]:
                route_best[rid] = contribution

    access_scores.append(sum(route_best.values()))

    # Raw counts for reference
    bus_counts.append(len(bus_tree.query(centroid.buffer(QUARTER_MI_M), predicate="intersects")))
    rail_counts.append(
        len(rail_tree.query(centroid.buffer(HALF_MI_M), predicate="intersects"))
    )

hex_gdf["bus_stops_quarter_mi"] = bus_counts
hex_gdf["rail_stations_half_mi"] = rail_counts
hex_gdf["access_score"] = access_scores

print(f"  Access score range: {min(access_scores):.2f} – {max(access_scores):.2f}")

# ---------------------------------------------------------------------------
# Filter to populated hexes
# ---------------------------------------------------------------------------
populated = hex_gdf[hex_gdf["density_mi2"] > DENSITY_THRESHOLD].copy()
print(f"  Populated hexes (>{DENSITY_THRESHOLD} persons/mi²): {len(populated)} of {len(hex_gdf)}")

effective_zeros = (populated["access_score"] < 0.01).sum()
print(f"  Effective zeros (access_score < 0.01): {effective_zeros} ({effective_zeros/len(populated)*100:.1f}%)")

# ---------------------------------------------------------------------------
# Decile scoring
# ---------------------------------------------------------------------------
N_STRATA = 10
print(f"Computing percentile-within-density-decile scores ({N_STRATA} strata)...")
decile_pcts = np.linspace(0, 100, N_STRATA + 1)
decile_cuts = np.percentile(populated["density_mi2"], decile_pcts)
decile_cuts[0] -= 1  # ensure lowest value is included

print(f"  Density decile boundaries: {[round(q) for q in decile_cuts]}")

populated["density_stratum"] = pd.cut(
    populated["density_mi2"], bins=decile_cuts,
    labels=list(range(1, N_STRATA + 1)), include_lowest=True
).astype(int)

populated["pct_rank"] = 0.0
for stratum in range(1, N_STRATA + 1):
    mask = populated["density_stratum"] == stratum
    if mask.sum() == 0:
        continue
    populated.loc[mask, "pct_rank"] = scipy_stats.rankdata(
        populated.loc[mask, "access_score"]
    ) / mask.sum()
    print(f"  Stratum {stratum}: {mask.sum()} hexes")

populated["deficit"] = populated["pct_rank"] - 0.5

print(f"\n  Deficit range: {populated['deficit'].min():.3f} to {populated['deficit'].max():.3f}")

# Label top transit deserts
top_deserts = populated.nsmallest(20, "deficit")
print("\nTop 10 transit deserts (most underserved for density peer group):")
for _, row in top_deserts.head(10).iterrows():
    print(f"  hex={row['hex_id'][:8]}... density={row['density_mi2']:.0f}/mi² "
          f"access={row['access_score']:.3f} stratum={row['density_stratum']} deficit={row['deficit']:.3f}")

# ---------------------------------------------------------------------------
# Neighborhood labels
# ---------------------------------------------------------------------------
NEIGHBORHOOD_PATH = DATA_DIR / "la_neighborhoods.geojson"

if not NEIGHBORHOOD_PATH.exists():
    print("\nDownloading LA Times neighborhood boundaries...")
    try:
        import requests
        resp = requests.get(
            "https://s3-us-west-2.amazonaws.com/boundaries.latimes.com/"
            "archive/1.0/boundary-set/la-county-neighborhoods-v6.geojson",
            timeout=30,
        )
        resp.raise_for_status()
        NEIGHBORHOOD_PATH.write_bytes(resp.content)
        print("  Downloaded.")
    except Exception as e:
        print(f"  Could not download neighborhoods: {e}")
        print("  Hexes will not have neighborhood labels.")

if NEIGHBORHOOD_PATH.exists():
    print("Labeling hexes with neighborhoods...")
    neighborhoods = gpd.read_file(NEIGHBORHOOD_PATH).to_crs("EPSG:4326")
    name_col = None
    for col in ["name", "NAME", "Name", "neighborhood", "NEIGHBORHOOD"]:
        if col in neighborhoods.columns:
            name_col = col
            break
    if name_col:
        hex_centroids_4326 = populated.copy()
        hex_centroids_4326 = hex_centroids_4326.to_crs("EPSG:3310")
        hex_centroids_4326["centroid"] = hex_centroids_4326.geometry.centroid
        hex_centroids_4326 = hex_centroids_4326.set_geometry("centroid")
        neighborhoods_3310 = neighborhoods.to_crs("EPSG:3310")
        joined = gpd.sjoin(hex_centroids_4326, neighborhoods_3310[[name_col, "geometry"]], how="left", predicate="within")
        joined = joined[~joined.index.duplicated(keep="first")]
        populated["neighborhood"] = joined.reindex(populated.index)[name_col].values
    else:
        print(f"  No name column found in neighborhoods. Columns: {list(neighborhoods.columns)}")
        populated["neighborhood"] = None
else:
    populated["neighborhood"] = None

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
print("\nSaving hex_transit_deserts.geojson...")
output_cols = ["hex_id", "geometry", "population", "area_mi2", "density_mi2",
               "bus_stops_quarter_mi", "rail_stations_half_mi", "access_score",
               "pct_rank", "density_stratum", "deficit", "neighborhood"]
output_cols = [c for c in output_cols if c in populated.columns]
populated[output_cols].to_file(DATA_DIR / "hex_transit_deserts.geojson", driver="GeoJSON")
print("Done.")
