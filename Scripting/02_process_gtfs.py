"""
02_process_gtfs.py
==================
Parse GTFS feeds (16 LA County transit agencies) to produce:
  - Data/transit_routes.geojson     → LineString per route with metadata
  - Data/transit_stops.geojson      → Point per stop with metadata + service metrics
  - Data/stop_route_trips.csv       → per-route weekday trip counts per stop

Run from project root:
    python Scripting/02_process_gtfs.py
"""

import sys
import zipfile
from datetime import timedelta
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
ROUTES_OUTPUT = DATA_DIR / "transit_routes.geojson"
STOPS_OUTPUT = DATA_DIR / "transit_stops.geojson"
STOP_ROUTE_OUTPUT = DATA_DIR / "stop_route_trips.csv"

# --- Original 4 feeds ---
BUS_GTFS_DIR = DATA_DIR / "la_metro_gtfs_bus"
RAIL_GTFS_DIR = DATA_DIR / "la_metro_gtfs_rail"
METROLINK_ZIP = DATA_DIR / "metrolink_gtfs.zip"
METROLINK_GTFS_DIR = DATA_DIR / "metrolink_gtfs"
BBB_ZIP = DATA_DIR / "big_blue_bus_current.zip"
BBB_GTFS_DIR = DATA_DIR / "big_blue_bus_gtfs"

# --- New feeds (zip → unzip dir) ---
NEW_FEEDS = [
    ("foothill_transit_gtfs.zip",   "foothill_transit_gtfs",   "foothill_transit"),
    ("ladot_gtfs.zip",             "ladot_gtfs",              "ladot"),
    ("long_beach_transit_gtfs.zip", "long_beach_transit_gtfs", "long_beach_transit"),
    ("montebello_gtfs.zip",        "montebello_gtfs",         "montebello"),
    ("culver_citybus_gtfs.zip",    "culver_citybus_gtfs",     "culver_citybus"),
    ("santa_clarita_gtfs.zip",     "santa_clarita_gtfs",      "santa_clarita"),
    ("avta_gtfs.zip",              "avta_gtfs",               "avta"),
    ("pasadena_transit_gtfs.zip",  "pasadena_transit_gtfs",   "pasadena_transit"),
    ("gtrans_gtfs.zip",           "gtrans_gtfs",              "gtrans"),
    ("norwalk_transit_gtfs.zip",   "norwalk_transit_gtfs",    "norwalk_transit"),
    ("glendale_beeline_gtfs.zip",  "glendale_beeline_gtfs",   "glendale_beeline"),
    ("torrance_transit_gtfs.zip",  "torrance_transit_gtfs",   "torrance_transit"),
    ("burbankbus_gtfs.zip",        "burbankbus_gtfs",         "burbankbus"),
    ("el_monte_transit_gtfs.zip",  "el_monte_transit_gtfs",   "el_monte_transit"),
    ("pvpta_gtfs.zip",             "pvpta_gtfs",              "pvpta"),
    ("lagobus_gtfs.zip",           "lagobus_gtfs",            "lagobus"),
    ("lawndale_beat_gtfs.zip",     "lawndale_beat_gtfs",      "lawndale_beat"),
    ("alhambra_transit_gtfs.zip",  "alhambra_transit_gtfs",   "alhambra_transit"),
    ("arcadia_transit_gtfs.zip",   "arcadia_transit_gtfs",    "arcadia_transit"),
    ("baldwin_park_transit_gtfs.zip", "baldwin_park_transit_gtfs", "baldwin_park_transit"),
    ("bellflower_bus_gtfs.zip",    "bellflower_bus_gtfs",     "bellflower_bus"),
    ("bell_gardens_trolley_gtfs.zip", "bell_gardens_trolley_gtfs", "bell_gardens_trolley"),
    ("compton_renaissance_gtfs.zip", "compton_renaissance_gtfs", "compton_renaissance"),
    ("cudahy_transit_gtfs.zip",    "cudahy_transit_gtfs",     "cudahy_transit"),
    ("downeylink_gtfs.zip",        "downeylink_gtfs",         "downeylink"),
    ("huntington_park_gtfs.zip",   "huntington_park_gtfs",    "huntington_park"),
    ("la_puente_link_gtfs.zip",    "la_puente_link_gtfs",     "la_puente_link"),
    ("lynwood_breeze_gtfs.zip",    "lynwood_breeze_gtfs",     "lynwood_breeze"),
    ("gate_south_gate_gtfs.zip",   "gate_south_gate_gtfs",    "gate_south_gate"),
    ("glendora_transit_gtfs.zip",  "glendora_transit_gtfs",   "glendora_transit"),
    ("go_west_transit_gtfs.zip",   "go_west_transit_gtfs",    "go_west_transit"),
    ("beach_cities_transit_gtfs.zip", "beach_cities_transit_gtfs", "beach_cities_transit"),
    ("rosemead_explorer_gtfs.zip", "rosemead_explorer_gtfs",  "rosemead_explorer"),
    ("sierra_madre_gtfs.zip",      "sierra_madre_gtfs",       "sierra_madre"),
    ("commerce_transit_gtfs.zip",  "commerce_transit_gtfs",   "commerce_transit"),
    ("cerritos_cow_gtfs.zip",      "cerritos_cow_gtfs",       "cerritos_cow"),
]

# Metrolink shape_id prefix → route_id mapping (trips.txt has no shape_id)
METROLINK_SHAPE_ROUTE = {
    "91": "91 Line",
    "AV": "Antelope Valley Line",
    "IEOC": "Inland Emp.-Orange Co. Line",
    "OC": "Orange County Line",
    "RIVER": "Riverside Line",
    "SB": "San Bernardino Line",
    "VT": "Ventura County Line",
}

# Category to assign based on feed name
FEED_CATEGORY = {
    "metro_bus": "metro_bus",
    "metro_rail": "metro_rail",
    "metrolink": "commuter_rail",
    "big_blue_bus": "local_bus",
    "foothill_transit": "local_bus",
    "ladot": "local_bus",
    "long_beach_transit": "local_bus",
    "montebello": "local_bus",
    "culver_citybus": "local_bus",
    "santa_clarita": "local_bus",
    "avta": "local_bus",
    "pasadena_transit": "local_bus",
    "gtrans": "local_bus",
    "norwalk_transit": "local_bus",
    "glendale_beeline": "local_bus",
    "torrance_transit": "local_bus",
    "burbankbus": "local_bus",
    "el_monte_transit": "local_bus",
    "pvpta": "local_bus",
    "lagobus": "local_bus",
    "lawndale_beat": "local_bus",
    "alhambra_transit": "local_bus",
    "arcadia_transit": "local_bus",
    "baldwin_park_transit": "local_bus",
    "bellflower_bus": "local_bus",
    "bell_gardens_trolley": "local_bus",
    "compton_renaissance": "local_bus",
    "cudahy_transit": "local_bus",
    "downeylink": "local_bus",
    "huntington_park": "local_bus",
    "la_puente_link": "local_bus",
    "lynwood_breeze": "local_bus",
    "gate_south_gate": "local_bus",
    "glendora_transit": "local_bus",
    "go_west_transit": "local_bus",
    "beach_cities_transit": "local_bus",
    "rosemead_explorer": "local_bus",
    "sierra_madre": "local_bus",
    "commerce_transit": "local_bus",
    "cerritos_cow": "local_bus",
}


# ---------------------------------------------------------------------------
# Helper: auto-unzip
# ---------------------------------------------------------------------------
def ensure_unzipped(zip_path: Path, target_dir: Path):
    """Extract zip if target directory doesn't exist."""
    if target_dir.exists():
        print(f"  {target_dir.name}/ already exists, skipping unzip")
        return
    if not zip_path.exists():
        print(f"  WARNING: {zip_path} not found, skipping")
        return
    print(f"  Extracting {zip_path.name} → {target_dir.name}/ ...")
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(target_dir)


# ---------------------------------------------------------------------------
# Helper: load a single GTFS feed and return route shapes + stops
# ---------------------------------------------------------------------------
def load_feed(gtfs_dir: Path, feed_name: str):
    """
    Parse a GTFS directory using raw pandas.
    Returns:
        routes_gdf      : GeoDataFrame of LineStrings per route
        stops_gdf       : GeoDataFrame of Points per stop (with service metrics)
        stop_route_df   : DataFrame of (stop_id, route_id, trips_per_day)
    """
    if not gtfs_dir.exists():
        print(f"  WARNING: {gtfs_dir} not found, skipping {feed_name}")
        return None, None, None

    print(f"  Loading {feed_name} from {gtfs_dir} ...")

    category = FEED_CATEGORY.get(feed_name, "bus")

    # -- Read required files --
    routes = pd.read_csv(gtfs_dir / "routes.txt", dtype=str)
    trips = pd.read_csv(gtfs_dir / "trips.txt", dtype=str)
    stops = pd.read_csv(gtfs_dir / "stops.txt", dtype=str)

    shapes_path = gtfs_dir / "shapes.txt"
    if not shapes_path.exists():
        print(f"    WARNING: shapes.txt not found in {gtfs_dir}, skipping routes")
        s_gdf = _build_stops_gdf(stops, feed_name, category)
        srt = _compute_stop_route_metrics(gtfs_dir, feed_name, category, stops)
        if not srt.empty:
            totals = srt.groupby("stop_id").agg(
                trips_per_day=("trips_per_day", "sum"),
                n_routes=("route_id", "nunique"),
            ).reset_index()
            s_gdf = s_gdf.merge(totals, on="stop_id", how="left")
        for col in ("trips_per_day", "n_routes"):
            s_gdf[col] = s_gdf[col].fillna(0).astype(int) if col in s_gdf.columns else 0
        return None, s_gdf, srt

    shapes = pd.read_csv(shapes_path, dtype=str)
    if shapes.empty:
        print(f"    WARNING: shapes.txt is empty in {gtfs_dir}, skipping routes")
        s_gdf = _build_stops_gdf(stops, feed_name, category)
        srt = _compute_stop_route_metrics(gtfs_dir, feed_name, category, stops)
        if not srt.empty:
            totals = srt.groupby("stop_id").agg(
                trips_per_day=("trips_per_day", "sum"),
                n_routes=("route_id", "nunique"),
            ).reset_index()
            s_gdf = s_gdf.merge(totals, on="stop_id", how="left")
        for col in ("trips_per_day", "n_routes"):
            s_gdf[col] = s_gdf[col].fillna(0).astype(int) if col in s_gdf.columns else 0
        return None, s_gdf, srt

    # -- Build LineStrings from shapes.txt --
    shapes["shape_pt_lat"] = pd.to_numeric(shapes["shape_pt_lat"])
    shapes["shape_pt_lon"] = pd.to_numeric(shapes["shape_pt_lon"])
    shapes["shape_pt_sequence"] = pd.to_numeric(shapes["shape_pt_sequence"])

    shapes_sorted = shapes.sort_values(["shape_id", "shape_pt_sequence"])

    shape_lines = (
        shapes_sorted
        .groupby("shape_id")
        .apply(lambda g: LineString(zip(g["shape_pt_lon"], g["shape_pt_lat"])))
        .reset_index()
        .rename(columns={0: "geometry"})
    )

    # -- Map shape → route via trips.txt --
    if "shape_id" in trips.columns:
        # Standard: join through trips
        trip_route = trips[["route_id", "shape_id"]].drop_duplicates(subset="shape_id")
        shape_route = shape_lines.merge(trip_route[["shape_id", "route_id"]], on="shape_id", how="left")
    else:
        # Metrolink fallback: match shape_id prefix to route_id
        print(f"    No shape_id in trips — using prefix mapping for {feed_name}")
        shape_lines["route_id"] = shape_lines["shape_id"].apply(_metrolink_shape_to_route)
        shape_route = shape_lines

    # -- Merge route metadata --
    routes["route_type"] = pd.to_numeric(routes["route_type"], errors="coerce")
    route_meta = routes[["route_id", "route_short_name", "route_long_name", "route_type", "route_color"]].copy()
    shape_route = shape_route.merge(route_meta, on="route_id", how="left")

    # -- Deduplicate: keep one shape per route (longest) --
    shape_route["_len"] = shape_route["geometry"].apply(lambda g: g.length if g else 0)
    shape_route = (
        shape_route.sort_values("_len", ascending=False)
        .drop_duplicates(subset="route_id")
        .drop(columns="_len")
    )

    # -- Drop phantom rows where route_id is null --
    shape_route = shape_route.dropna(subset=["route_id"])

    # -- Assign route category --
    shape_route["route_category"] = category
    shape_route["feed"] = feed_name

    routes_gdf = gpd.GeoDataFrame(shape_route, geometry="geometry", crs="EPSG:4326")

    # -- For rail feeds, keep only station-level stops (drop platforms & entrances) --
    all_stops_df = stops  # keep unfiltered for parent_station mapping
    if category in ("metro_rail", "commuter_rail") and "location_type" in stops.columns:
        stations = stops[stops["location_type"] == "1"]
        if not stations.empty:
            stops = stations

    stops_gdf = _build_stops_gdf(stops, feed_name, category)

    # -- Compute per-stop service metrics (all feeds) --
    stop_route_df = _compute_stop_route_metrics(gtfs_dir, feed_name, category, all_stops_df)
    if not stop_route_df.empty:
        totals = stop_route_df.groupby("stop_id").agg(
            trips_per_day=("trips_per_day", "sum"),
            n_routes=("route_id", "nunique"),
        ).reset_index()
        stops_gdf = stops_gdf.merge(totals, on="stop_id", how="left")
    for col in ("trips_per_day", "n_routes"):
        stops_gdf[col] = stops_gdf[col].fillna(0).astype(int) if col in stops_gdf.columns else 0

    # -- Rail: add route_color for line-colored station markers --
    if category in ("metro_rail", "commuter_rail"):
        stop_times_path = gtfs_dir / "stop_times.txt"
        if stop_times_path.exists():
            stop_times = pd.read_csv(stop_times_path, dtype=str, usecols=["trip_id", "stop_id"])
            stop_routes = (
                stop_times.merge(trips[["trip_id", "route_id"]], on="trip_id")
                [["stop_id", "route_id"]]
                .drop_duplicates()
            )
            if "parent_station" in all_stops_df.columns:
                parent_map = all_stops_df[["stop_id", "parent_station"]].copy()
                parent_map["parent_station"] = parent_map["parent_station"].replace("", pd.NA)
                stop_routes = stop_routes.merge(parent_map, on="stop_id", how="left")
                stop_routes["station_id"] = stop_routes["parent_station"].fillna(stop_routes["stop_id"])
            else:
                stop_routes["station_id"] = stop_routes["stop_id"]

            station_routes = stop_routes[["station_id", "route_id"]].drop_duplicates()
            single_ids = station_routes.groupby("station_id").filter(
                lambda x: len(x) == 1
            )["station_id"]
            single_colors = (
                station_routes[station_routes["station_id"].isin(single_ids)]
                .merge(routes[["route_id", "route_color"]], on="route_id")
                [["station_id", "route_color"]]
                .drop_duplicates()
                .rename(columns={"station_id": "stop_id"})
            )
            stops_gdf = stops_gdf.merge(single_colors, on="stop_id", how="left")

    print(f"    {len(routes_gdf)} routes, {len(stops_gdf)} stops, "
          f"{len(stop_route_df)} stop-route pairs")
    return routes_gdf, stops_gdf, stop_route_df


def _metrolink_shape_to_route(shape_id: str) -> str:
    """Map a Metrolink shape_id like '91in' or 'AVout' to a route_id."""
    prefix = shape_id.rstrip("inout")
    # Handle edge case: strip trailing 'in' or 'out'
    for suffix in ("in", "out"):
        if shape_id.endswith(suffix):
            prefix = shape_id[: -len(suffix)]
            break
    return METROLINK_SHAPE_ROUTE.get(prefix, shape_id)


def _build_stops_gdf(stops: pd.DataFrame, feed_name: str, category: str) -> gpd.GeoDataFrame:
    stops = stops.copy()
    stops["stop_lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["stop_lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")
    stops = stops.dropna(subset=["stop_lat", "stop_lon"])
    stops["geometry"] = stops.apply(lambda r: Point(r["stop_lon"], r["stop_lat"]), axis=1)
    stops["feed"] = feed_name
    stops["route_category"] = category
    return gpd.GeoDataFrame(
        stops[["stop_id", "stop_name", "stop_lat", "stop_lon", "feed", "route_category", "geometry"]],
        geometry="geometry",
        crs="EPSG:4326",
    )


def _get_weekday_service_ids(gtfs_dir: Path) -> set:
    """Return set of service_ids active on a representative Tuesday.

    Prefers calendar_dates.txt for target date selection (handles feeds
    where trips reference service_ids only defined in calendar_dates).
    """
    cal_path = gtfs_dir / "calendar.txt"
    cd_path = gtfs_dir / "calendar_dates.txt"

    active = set()
    target = None
    cd = None

    # Step 1: pick a target Tuesday — prefer calendar_dates if it has them
    if cd_path.exists():
        cd = pd.read_csv(cd_path, dtype=str)
        dates = pd.to_datetime(cd["date"], format="%Y%m%d")
        tuesdays = dates[dates.dt.weekday == 1]
        if not tuesdays.empty:
            target = tuesdays.iloc[len(tuesdays) // 2]
        else:
            weekdays = dates[dates.dt.weekday < 5]
            if not weekdays.empty:
                target = weekdays.iloc[len(weekdays) // 2]

    if target is None and cal_path.exists():
        cal = pd.read_csv(cal_path, dtype=str)
        start_dates = pd.to_datetime(cal["start_date"], format="%Y%m%d")
        end_dates = pd.to_datetime(cal["end_date"], format="%Y%m%d")
        mid = start_dates.min() + (end_dates.max() - start_dates.min()) / 2
        days_until_tue = (1 - mid.weekday()) % 7
        target = mid + timedelta(days=days_until_tue)

    # Step 2: find active services from calendar.txt base schedule
    if cal_path.exists() and target is not None:
        cal = pd.read_csv(cal_path, dtype=str)
        for _, row in cal.iterrows():
            s = pd.to_datetime(row["start_date"], format="%Y%m%d")
            e = pd.to_datetime(row["end_date"], format="%Y%m%d")
            if s <= target <= e and row.get("tuesday", "0") == "1":
                active.add(row["service_id"])

    # Step 3: apply calendar_dates exceptions for the target date
    if cd is not None and target is not None:
        target_str = target.strftime("%Y%m%d")
        for _, row in cd.iterrows():
            if row["date"] == target_str:
                if row["exception_type"] == "1":
                    active.add(row["service_id"])
                elif row["exception_type"] == "2":
                    active.discard(row["service_id"])

    # Fallback: use all service_ids if nothing matched
    if not active:
        trips_path = gtfs_dir / "trips.txt"
        if trips_path.exists():
            t = pd.read_csv(trips_path, dtype=str, usecols=["service_id"])
            active = set(t["service_id"].unique())

    return active


def _compute_stop_route_metrics(gtfs_dir: Path, feed_name: str, category: str,
                                all_stops_df: pd.DataFrame) -> pd.DataFrame:
    """Compute weekday trips per (stop, route) combination.

    Returns DataFrame with columns: stop_id, route_id, trips_per_day.
    Route IDs are prefixed with feed_name for global uniqueness.
    For rail feeds, platform stop_ids are mapped to parent station stop_ids.
    """
    st_path = gtfs_dir / "stop_times.txt"
    trips_path = gtfs_dir / "trips.txt"
    empty = pd.DataFrame(columns=["stop_id", "route_id", "trips_per_day"])

    if not st_path.exists() or not trips_path.exists():
        return empty

    service_ids = _get_weekday_service_ids(gtfs_dir)
    trips = pd.read_csv(trips_path, dtype=str)
    if "service_id" in trips.columns:
        trips = trips[trips["service_id"].isin(service_ids)]
    if trips.empty:
        return empty

    stop_times = pd.read_csv(st_path, dtype=str, usecols=["trip_id", "stop_id"])
    merged = stop_times.merge(trips[["trip_id", "route_id"]], on="trip_id")

    # For rail: map platform stop_ids → parent station stop_ids
    if category in ("metro_rail", "commuter_rail") and "parent_station" in all_stops_df.columns:
        parent_map = all_stops_df[["stop_id", "parent_station"]].copy()
        parent_map["parent_station"] = parent_map["parent_station"].replace("", pd.NA)
        merged = merged.merge(parent_map, on="stop_id", how="left")
        merged["stop_id"] = merged["parent_station"].fillna(merged["stop_id"])
        merged = merged.drop(columns=["parent_station"])

    # Prefix route_ids for global uniqueness across feeds
    merged["route_id"] = feed_name + ":" + merged["route_id"]

    result = (
        merged.groupby(["stop_id", "route_id"])["trip_id"]
        .nunique()
        .reset_index()
        .rename(columns={"trip_id": "trips_per_day"})
    )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
print("Processing GTFS feeds...")

# Auto-unzip original feeds
ensure_unzipped(METROLINK_ZIP, METROLINK_GTFS_DIR)
ensure_unzipped(BBB_ZIP, BBB_GTFS_DIR)

# Auto-unzip new feeds
for zip_name, dir_name, _ in NEW_FEEDS:
    ensure_unzipped(DATA_DIR / zip_name, DATA_DIR / dir_name)

# Load original four feeds
bus_routes, bus_stops, bus_srt = load_feed(BUS_GTFS_DIR, "metro_bus")
rail_routes, rail_stops, rail_srt = load_feed(RAIL_GTFS_DIR, "metro_rail")
metrolink_routes, metrolink_stops, metrolink_srt = load_feed(METROLINK_GTFS_DIR, "metrolink")
bbb_routes, bbb_stops, bbb_srt = load_feed(BBB_GTFS_DIR, "big_blue_bus")

routes_parts = [r for r in [bus_routes, rail_routes, metrolink_routes, bbb_routes] if r is not None]
stops_parts = [s for s in [bus_stops, rail_stops, metrolink_stops, bbb_stops] if s is not None]
srt_parts = [t for t in [bus_srt, rail_srt, metrolink_srt, bbb_srt] if t is not None and not t.empty]

# Load new feeds
for _, dir_name, feed_name in NEW_FEEDS:
    gtfs_dir = DATA_DIR / dir_name
    r, s, t = load_feed(gtfs_dir, feed_name)
    if r is not None:
        routes_parts.append(r)
    if s is not None:
        stops_parts.append(s)
    if t is not None and not t.empty:
        srt_parts.append(t)

if not routes_parts:
    sys.exit("ERROR: No route data loaded from any GTFS feed")

all_routes = pd.concat(routes_parts, ignore_index=True)
all_routes_gdf = gpd.GeoDataFrame(all_routes, geometry="geometry", crs="EPSG:4326")

# Promote J Line (Silver BRT) and G Line (Orange BRT) to metro_rail
brt_mask = all_routes_gdf["route_long_name"].str.contains("J Line|G Line", na=False)
if brt_mask.any():
    promoted = all_routes_gdf.loc[brt_mask, "route_long_name"].tolist()
    all_routes_gdf.loc[brt_mask, "route_category"] = "metro_rail"
    print(f"\n  Promoted BRT → metro_rail: {promoted}")

# Combine stops
all_stops = pd.concat(stops_parts, ignore_index=True)
all_stops_gdf = gpd.GeoDataFrame(all_stops, geometry="geometry", crs="EPSG:4326")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\nRoutes summary:")
print(f"  Total routes: {len(all_routes_gdf)}")
for cat in sorted(all_routes_gdf["route_category"].unique()):
    count = (all_routes_gdf["route_category"] == cat).sum()
    print(f"  {cat}: {count}")
print(f"\nStops summary:")
print(f"  Total stops: {len(all_stops_gdf)}")
for cat in sorted(all_stops_gdf["route_category"].unique()):
    count = (all_stops_gdf["route_category"] == cat).sum()
    print(f"  {cat}: {count}")

# Combine stop-route trip data
all_srt = pd.concat(srt_parts, ignore_index=True) if srt_parts else pd.DataFrame()
print(f"\nStop-route trip pairs: {len(all_srt)}")
if not all_srt.empty:
    print(f"  Unique routes: {all_srt['route_id'].nunique()}")
    print(f"  Trips/stop-route: median={all_srt['trips_per_day'].median():.0f}, "
          f"mean={all_srt['trips_per_day'].mean():.0f}, "
          f"max={all_srt['trips_per_day'].max()}")

# Service metrics summary
if "trips_per_day" in all_stops_gdf.columns:
    active = all_stops_gdf[all_stops_gdf["trips_per_day"] > 0]
    print(f"\nStops with weekday service: {len(active)} of {len(all_stops_gdf)}")
    print(f"  Trips/day: median={active['trips_per_day'].median():.0f}, "
          f"mean={active['trips_per_day'].mean():.0f}, "
          f"max={active['trips_per_day'].max()}")
    print(f"  Routes/stop: median={active['n_routes'].median():.0f}, "
          f"max={active['n_routes'].max()}")

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
print(f"\nSaving routes to {ROUTES_OUTPUT} ...")
all_routes_gdf = all_routes_gdf[all_routes_gdf.geometry.notna()]
all_routes_gdf.to_file(ROUTES_OUTPUT, driver="GeoJSON")

print(f"Saving stops to {STOPS_OUTPUT} ...")
all_stops_gdf = all_stops_gdf[all_stops_gdf.geometry.notna()]
all_stops_gdf.to_file(STOPS_OUTPUT, driver="GeoJSON")

if not all_srt.empty:
    print(f"Saving stop-route trips to {STOP_ROUTE_OUTPUT} ...")
    all_srt.to_csv(STOP_ROUTE_OUTPUT, index=False)

print("\nDone.")
