"""
03_build_map.py
===============
Build an interactive Folium map overlaying:
  1. Population density choropleth (census tracts, YlOrRd)
  2. Metro Rail lines (official brand colors, bold)
  3. Metrolink commuter rail lines (brand colors, bold)
  4. Metro Bus routes (orange, semi-transparent)
  5. Big Blue Bus routes (brand colors, off by default)
  6. Separate stop layers per transit system (off by default)

Visual enhancements: dark basemap toggle, rail line legend,
Fullscreen control, MiniMap, MarkerCluster for bus stops.

Output: Outputs/la_transit_density_map.html

Run from project root:
    python Scripting/03_build_map.py
"""

import json
import sys
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
from branca.colormap import LinearColormap
from branca.element import MacroElement, Template
from folium.plugins import Fullscreen, MiniMap, MarkerCluster

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
OUTPUT_DIR = PROJECT_ROOT / "Outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

DENSITY_PATH = DATA_DIR / "la_tracts_density.geojson"
ROUTES_PATH = DATA_DIR / "transit_routes.geojson"
STOPS_PATH = DATA_DIR / "transit_stops.geojson"
OUTPUT_HTML = OUTPUT_DIR / "la_transit_density_map.html"

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
print("Loading data...")

for p in [DENSITY_PATH, ROUTES_PATH, STOPS_PATH]:
    if not p.exists():
        sys.exit(f"ERROR: Required file not found: {p}\nRun scripts 01 and 02 first.")

density_gdf = gpd.read_file(DENSITY_PATH)
routes_gdf = gpd.read_file(ROUTES_PATH)
stops_gdf = gpd.read_file(STOPS_PATH)

print(f"  Tracts: {len(density_gdf)}, Routes: {len(routes_gdf)}, Stops: {len(stops_gdf)}")

# Ensure WGS84
density_gdf = density_gdf.to_crs("EPSG:4326")
routes_gdf = routes_gdf.to_crs("EPSG:4326")
stops_gdf = stops_gdf.to_crs("EPSG:4326")

# ---------------------------------------------------------------------------
# Colormap for density
# ---------------------------------------------------------------------------
density_col = "density"
valid_density = density_gdf[density_col].dropna()
vmin, vmax = float(valid_density.quantile(0.02)), float(valid_density.quantile(0.98))

colormap = LinearColormap(
    colors=["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"],
    vmin=vmin,
    vmax=vmax,
    caption="Population Density (persons / km²)",
)


def density_style(feature):
    val = feature["properties"].get(density_col)
    if val is None or pd.isna(val):
        return {"fillColor": "#f0f0f0", "color": "#cccccc", "weight": 0.3, "fillOpacity": 0.6}
    return {
        "fillColor": colormap(min(max(val, vmin), vmax)),
        "color": "#888888",
        "weight": 0.3,
        "fillOpacity": 0.7,
    }


def density_highlight(feature):
    return {"weight": 1.5, "color": "#333333", "fillOpacity": 0.85}


# ---------------------------------------------------------------------------
# Route styling helpers
# ---------------------------------------------------------------------------
RAIL_DEFAULT_COLOR = "#1a1aff"
BUS_COLOR = "#ff6600"
NEUTRAL_STATION_COLOR = "#CCCCCC"  # multi-line transfer stations


def get_route_color(feature):
    rc = feature["properties"].get("route_color") or ""
    if rc and len(rc) == 6:
        return f"#{rc}"
    category = feature["properties"].get("route_category", "metro_bus")
    if category in ("metro_rail", "commuter_rail"):
        return RAIL_DEFAULT_COLOR
    return BUS_COLOR


def rail_style(feature):
    return {
        "color": get_route_color(feature),
        "weight": 4,
        "opacity": 0.9,
    }


def bus_style(feature):
    return {
        "color": BUS_COLOR,
        "weight": 1.5,
        "opacity": 0.55,
    }


def metrolink_style(feature):
    """Metrolink — brand colors at reduced opacity."""
    return {
        "color": get_route_color(feature),
        "weight": 4,
        "opacity": 0.5,
    }


def bbb_style(feature):
    """Big Blue Bus — transparent blue, matching Metro Bus weight/opacity."""
    return {
        "color": "#4A90D9",
        "weight": 1.5,
        "opacity": 0.55,
    }


# ---------------------------------------------------------------------------
# Layer configuration
# ---------------------------------------------------------------------------
ROUTE_LAYERS = [
    # Ordered bottom → top for z-ordering
    {
        "category": "metro_bus",
        "name": "Metro Bus Routes",
        "show": True,
        "style_fn": bus_style,
        "tooltip_fields": ["route_short_name", "route_long_name"],
        "tooltip_aliases": ["Route", "Name"],
    },
    {
        "category": "local_bus",
        "name": "Big Blue Bus Routes",
        "show": False,
        "style_fn": bbb_style,
        "tooltip_fields": ["route_short_name", "route_long_name"],
        "tooltip_aliases": ["Route", "Name"],
    },
    {
        "category": "commuter_rail",
        "name": "Metrolink Lines",
        "show": True,
        "style_fn": metrolink_style,
        "tooltip_fields": ["route_short_name", "route_long_name"],
        "tooltip_aliases": ["Line", "Name"],
    },
    {
        "category": "metro_rail",
        "name": "Metro Rail Lines",
        "show": True,
        "style_fn": rail_style,
        "tooltip_fields": ["route_short_name", "route_long_name"],
        "tooltip_aliases": ["Line", "Name"],
    },
]

STOP_LAYERS = [
    {
        "category": "metro_rail",
        "name": "Metro Rail Stations",
        "show": False,
        "color": "#1a1aff",
        "radius": 5,
        "opacity": 0.9,
        "use_cluster": False,
    },
    {
        "category": "commuter_rail",
        "name": "Metrolink Stations",
        "show": False,
        "color": "#8B4513",
        "radius": 6,
        "opacity": 0.5,
        "use_cluster": False,
    },
    {
        "category": "metro_bus",
        "name": "Metro Bus Stops",
        "show": False,
        "color": BUS_COLOR,
        "radius": 2,
        "use_cluster": True,
    },
    {
        "category": "local_bus",
        "name": "Big Blue Bus Stops",
        "show": False,
        "color": "#0066cc",
        "radius": 2,
        "use_cluster": True,
    },
]


# ---------------------------------------------------------------------------
# Build map
# ---------------------------------------------------------------------------
print("Building Folium map...")

m = folium.Map(
    location=[34.0522, -118.2437],
    zoom_start=10,
    min_zoom=9,
    max_zoom=15,
    tiles=None,
)

# Positron basemap (sole basemap, no toggle)
folium.TileLayer(
    tiles="CartoDB Positron",
    name="CartoDB Positron",
    control=False,
).add_to(m)

# ---------------------------------------------------------------------------
# Custom panes for fixed z-ordering (survives layer toggle on/off)
# ---------------------------------------------------------------------------
ROUTE_PANE = {
    "metro_bus": "busRoutesPane",
    "local_bus": "busRoutesPane",
    "commuter_rail": "metrolinkRoutesPane",
    "metro_rail": "railRoutesPane",
}

pane_setup = MacroElement()
pane_setup._template = Template("""
    {% macro script(this, kwargs) %}
        var map = {{ this._parent.get_name() }};
        map.createPane('densityPane');
        map.getPane('densityPane').style.zIndex = 400;
        map.createPane('stopsPane');
        map.getPane('stopsPane').style.zIndex = 450;
        map.createPane('busRoutesPane');
        map.getPane('busRoutesPane').style.zIndex = 420;
        map.createPane('metrolinkRoutesPane');
        map.getPane('metrolinkRoutesPane').style.zIndex = 430;
        map.createPane('railRoutesPane');
        map.getPane('railRoutesPane').style.zIndex = 440;
    {% endmacro %}
""")
pane_setup.add_to(m)

# ---------------------------------------------------------------------------
# Layer 1: Population density choropleth
# ---------------------------------------------------------------------------
print("  Adding density layer...")

density_layer = folium.FeatureGroup(name="Population Density", show=True)

density_json = json.loads(density_gdf.to_json())

folium.GeoJson(
    density_json,
    name="Population Density",
    style_function=density_style,
    highlight_function=density_highlight,
    pane="densityPane",
    tooltip=folium.GeoJsonTooltip(
        fields=["NAME", "population", "density"],
        aliases=["Tract", "Population", "Density (per km²)"],
        localize=True,
        sticky=False,
        labels=True,
        style=(
            "background-color: white; color: #333333; font-family: Arial; "
            "font-size: 12px; padding: 6px; border-radius: 4px; "
            "box-shadow: 2px 2px 4px rgba(0,0,0,0.2);"
        ),
        max_width=250,
    ),
).add_to(density_layer)

density_layer.add_to(m)

# ---------------------------------------------------------------------------
# Stop layers (in stopsPane so they stay below routes)
# ---------------------------------------------------------------------------
for cfg in STOP_LAYERS:
    cat = cfg["category"]
    subset = stops_gdf[stops_gdf["route_category"] == cat].copy()
    if subset.empty:
        print(f"  Skipping {cfg['name']} (no stops)")
        continue

    print(f"  Adding {cfg['name']} ({len(subset)} stops)...")
    fg = folium.FeatureGroup(name=cfg["name"], show=cfg["show"])

    if cfg["use_cluster"]:
        cluster = MarkerCluster(name=cfg["name"])
        for _, row in subset.iterrows():
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=cfg["radius"],
                color=cfg["color"],
                fill=True,
                fill_color=cfg["color"],
                fill_opacity=0.6,
                weight=0,
                pane="stopsPane",
                tooltip=row.get("stop_name", ""),
            ).add_to(cluster)
        cluster.add_to(fg)
    else:
        stop_opacity = cfg.get("opacity", 0.9)
        for _, row in subset.iterrows():
            # Per-stop color based on line color (rail/commuter)
            n_routes = row.get("n_routes")
            if pd.notna(n_routes) and n_routes > 1:
                stop_color = NEUTRAL_STATION_COLOR
            else:
                rc = row.get("route_color")
                rc = str(rc) if pd.notna(rc) else ""
                stop_color = f"#{rc}" if len(rc) == 6 else cfg["color"]
            folium.CircleMarker(
                location=[row.geometry.y, row.geometry.x],
                radius=cfg["radius"],
                color="#333333",
                fill=True,
                fill_color=stop_color,
                fill_opacity=stop_opacity,
                opacity=stop_opacity,
                weight=2,
                pane="stopsPane",
                tooltip=row.get("stop_name", ""),
            ).add_to(fg)

    fg.add_to(m)

# ---------------------------------------------------------------------------
# Route layers (4 separate FeatureGroups, each in its own pane)
# ---------------------------------------------------------------------------
for cfg in ROUTE_LAYERS:
    cat = cfg["category"]
    subset = routes_gdf[routes_gdf["route_category"] == cat].copy()
    if subset.empty:
        print(f"  Skipping {cfg['name']} (no routes)")
        continue

    print(f"  Adding {cfg['name']} ({len(subset)} routes)...")
    fg = folium.FeatureGroup(name=cfg["name"], show=cfg["show"])

    folium.GeoJson(
        json.loads(subset.to_json()),
        name=cfg["name"],
        style_function=cfg["style_fn"],
        pane=ROUTE_PANE[cat],
        tooltip=folium.GeoJsonTooltip(
            fields=cfg["tooltip_fields"],
            aliases=cfg["tooltip_aliases"],
            localize=True,
            sticky=False,
            labels=True,
            style="background-color: white; font-family: Arial; font-size: 12px; padding: 4px;",
            max_width=200,
        ),
    ).add_to(fg)

    fg.add_to(m)

# ---------------------------------------------------------------------------
# Colormap legend (repositioned to bottom-center)
# ---------------------------------------------------------------------------
colormap.add_to(m)

# Override default colormap position to bottom-center
colormap_css = """
<style>
    .legend.leaflet-control {
        position: fixed !important;
        bottom: 10px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        top: auto !important;
        right: auto !important;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.92) !important;
        border-radius: 6px !important;
        padding: 6px 10px !important;
    }
    .legend.leaflet-control .caption {
        color: #333 !important;
    }
</style>
"""
m.get_root().html.add_child(folium.Element(colormap_css))

# ---------------------------------------------------------------------------
# Rail line legend (bottom-left)
# ---------------------------------------------------------------------------
print("  Building rail line legend...")

rail_categories = routes_gdf[routes_gdf["route_category"].isin(["metro_rail", "commuter_rail"])].copy()
if not rail_categories.empty:
    legend_items = []
    for _, row in rail_categories.iterrows():
        name_short = row.get("route_short_name")
        name_long = row.get("route_long_name")
        name = (name_short if pd.notna(name_short) else None) or \
               (name_long if pd.notna(name_long) else None) or "Unknown"
        rc = row.get("route_color")
        rc = str(rc) if pd.notna(rc) else ""
        color = f"#{rc}" if len(rc) == 6 else RAIL_DEFAULT_COLOR
        legend_items.append((name, color))

    # Sort: Metro Rail first, then Metrolink
    legend_rows_html = ""
    for name, color in legend_items:
        legend_rows_html += (
            f'<div style="display:flex;align-items:center;margin:2px 0;">'
            f'<span style="display:inline-block;width:24px;height:4px;'
            f'background:{color};margin-right:6px;border-radius:2px;"></span>'
            f'<span style="font-size:11px;color:#333;">{name}</span>'
            f'</div>'
        )

    legend_html = f"""
    <div id="rail-legend" style="
        position: fixed;
        bottom: 40px;
        left: 10px;
        z-index: 1000;
        background-color: rgba(255,255,255,0.92);
        padding: 8px 12px;
        border-radius: 6px;
        box-shadow: 2px 2px 6px rgba(0,0,0,0.2);
        font-family: Arial, sans-serif;
        max-height: 300px;
        overflow-y: auto;
    ">
        <div style="font-size: 12px; font-weight: bold; color: #222; margin-bottom: 4px;">
            Rail Lines
        </div>
        {legend_rows_html}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

# ---------------------------------------------------------------------------
# Map title (HTML overlay)
# ---------------------------------------------------------------------------
title_html = """
<div style="
    position: fixed;
    top: 15px;
    left: 60px;
    z-index: 1000;
    background-color: rgba(255,255,255,0.92);
    padding: 10px 16px;
    border-radius: 6px;
    box-shadow: 2px 2px 6px rgba(0,0,0,0.2);
    font-family: Arial, sans-serif;
    pointer-events: none;
">
    <div style="font-size: 16px; font-weight: bold; color: #222;">
        Los Angeles: Population Density &amp; Transit Network
    </div>
    <div style="font-size: 11px; color: #666; margin-top: 3px;">
        ACS 5-Year Estimates &nbsp;|&nbsp; LA Metro, Metrolink, Big Blue Bus GTFS
    </div>
</div>
"""
m.get_root().html.add_child(folium.Element(title_html))

# ---------------------------------------------------------------------------
# Fullscreen + MiniMap
# ---------------------------------------------------------------------------
Fullscreen(position="topleft").add_to(m)

# ---------------------------------------------------------------------------
# Layer control
# ---------------------------------------------------------------------------
folium.LayerControl(position="topright", collapsed=False).add_to(m)

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
print(f"Saving map to {OUTPUT_HTML} ...")
m.save(str(OUTPUT_HTML))

print(f"\nDone. Open in browser: {OUTPUT_HTML}")
