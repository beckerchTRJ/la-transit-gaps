/* ==========================================================================
   D3.js Visualizations for LA Transit Data Story
   ========================================================================== */

window.VIZ = {};

/* Cache-busting version — increment when data files change */
var DATA_V = "?v=" + Date.now();

/* Configurable data path prefix — test pages set window.DATA_BASE = "../data/" */
var DATA_BASE = window.DATA_BASE || "data/";

const COLORS = {
  bg: "#E8ECF0",
  accent: "#BD0026",
  text: "#222",
  textLight: "#666",
  bus: "#ff6600",
  rail: "#1a1aff",
  busRail: "#7b2d8e",
  none: "#ccc",
};

function fmt(n) {
  if (n == null) return "\u2014";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "K";
  return n.toLocaleString();
}

/* Precision-aware range label — falls back to full numbers when fmt would collide */
function fmtRange(lo, hi) {
  if (hi == null) return fmt(lo) + "+/mi\u00B2";
  var sLo = fmt(lo), sHi = fmt(hi);
  if (sLo === sHi) {
    sLo = lo.toLocaleString();
    sHi = hi.toLocaleString();
  }
  return sLo + " \u2013 " + sHi + "/mi\u00B2";
}

/* Shared: create SVG fitted to container */
function makeSvg(sel, ratio) {
  var el = d3.select(sel);
  var w = el.node().getBoundingClientRect().width || 800;
  var h = w * (ratio || 0.65);
  var svg = el.append("svg")
    .attr("viewBox", "0 0 " + w + " " + h)
    .attr("preserveAspectRatio", "xMidYMid meet");
  svg.append("rect").attr("width", w).attr("height", h)
    .attr("fill", COLORS.bg).attr("rx", 4);
  return { svg: svg, w: w, h: h };
}

/* Shared: fit projection to a GeoJSON boundary.
   Extracts raw coordinate bounds and fits to a CW rectangle, avoiding D3's
   spherical winding interpretation which miscalculates scale on MultiPolygons. */
function fitProjection(boundary, w, h, pad) {
  pad = pad || 30;
  var lngs = [], lats = [];
  function extract(c) {
    if (typeof c[0] === "number") { lngs.push(c[0]); lats.push(c[1]); }
    else c.forEach(extract);
  }
  (boundary.features || [boundary]).forEach(function (f) { extract((f.geometry || f).coordinates); });
  var west = d3.min(lngs), east = d3.max(lngs), south = d3.min(lats), north = d3.max(lats);
  var bbox = {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[west,south],[west,north],[east,north],[east,south],[west,south]]] },
    properties: {}
  };
  return d3.geoMercator().fitExtent([[pad, pad], [w - pad, h - pad]], bbox);
}

/* Reverse ring winding in GeoJSON for D3's spherical geoPath. */
function reverseWinding(geojson) {
  var copy = JSON.parse(JSON.stringify(geojson));
  copy.features.forEach(function (f) {
    var g = f.geometry;
    if (g.type === "Polygon") {
      g.coordinates.forEach(function (ring, i) { g.coordinates[i] = ring.slice().reverse(); });
    } else if (g.type === "MultiPolygon") {
      g.coordinates.forEach(function (poly) {
        poly.forEach(function (ring, i) { poly[i] = ring.slice().reverse(); });
      });
    }
  });
  return copy;
}

/* Shared: data fetch cache — avoids duplicate downloads across sections */
var _dataCache = {};
function cachedFetch(url) {
  var key = url.split("?")[0];
  if (_dataCache[key]) return Promise.resolve(_dataCache[key]);
  return fetch(url + DATA_V).then(function (r) { return r.json(); }).then(function (d) {
    _dataCache[key] = d;
    return d;
  });
}

/* ========================================================================
   Animated count-up utility
   ======================================================================== */
function animateCount(el, endVal, opts, onComplete) {
  opts = opts || {};
  var duration = opts.duration || 1800;
  var suffix = opts.suffix || "";
  var isFloat = opts.float || false;
  var formatFn = opts.format || null;
  var start = null;

  function easeOutCubic(t) { return 1 - Math.pow(1 - t, 3); }

  function step(ts) {
    if (!start) start = ts;
    var progress = Math.min((ts - start) / duration, 1);
    var eased = easeOutCubic(progress);
    var current = eased * endVal;

    if (formatFn) {
      el.textContent = formatFn(current) + suffix;
    } else if (isFloat) {
      el.textContent = current.toFixed(1) + suffix;
    } else {
      el.textContent = Math.round(current).toLocaleString() + suffix;
    }

    if (progress < 1) {
      requestAnimationFrame(step);
    } else if (onComplete) {
      onComplete();
    }
  }
  requestAnimationFrame(step);
}

/* ========================================================================
   Stat counter scroll-triggered animation system
   ======================================================================== */
var _statDataReady = { coverage: null, counterfactual: null };
var _statAnimated = {};

function tryAnimateStat(id) {
  if (_statAnimated[id]) return;
  var el = document.getElementById(id);
  if (!el) return;

  var val, suffix, formatFn;
  if (id === "stat-bus-pct" && _statDataReady.coverage) {
    val = _statDataReady.coverage.bus_quarter_mi.percent_covered;
    suffix = "%";
  } else if (id === "stat-rail-pct" && _statDataReady.coverage) {
    val = _statDataReady.coverage.rail_half_mi.percent_covered;
    suffix = "%";
  } else if (id === "stat-additional-pop" && _statDataReady.counterfactual) {
    val = _statDataReady.counterfactual.hypothetical_additional_population;
    suffix = "";
    formatFn = fmt;
  } else if (id === "stat-new-rail-pct" && _statDataReady.counterfactual) {
    // Three-step animation: current → +D Line → +hypothetical
    _statAnimated[id] = true;
    var cf = _statDataReady.counterfactual;
    var label = document.getElementById("stat-new-rail-label");
    // Step 1: animate to current rail coverage
    label.textContent = "current rail coverage";
    animateCount(el, cf.current_rail_1km_percent, { suffix: "%", float: true }, function () {
      // Step 2: after pause, bump to D Line
      setTimeout(function () {
        label.textContent = "with D Line extension (2025\u20132027)";
        el.style.transition = "color 0.4s";
        el.style.color = "#7b68ee";
        animateCount(el, cf.dline_total_percent, { suffix: "%", float: true, duration: 600 }, function () {
          // Step 3: after pause, animate to full hypothetical
          setTimeout(function () {
            label.textContent = "with 20 optimally placed stations";
            el.style.color = "#4575b4";
            animateCount(el, cf.final_total_percent, { suffix: "%", float: true, duration: 800 });
          }, 1200);
        });
      }, 1200);
    });
    return;
  } else if (id === "stat-n-stations" && _statDataReady.counterfactual) {
    val = _statDataReady.counterfactual.n_hypothetical_stations;
    suffix = "";
  } else {
    return; // data not ready yet
  }

  _statAnimated[id] = true;
  animateCount(el, val, {
    suffix: suffix,
    format: formatFn || null,
    float: typeof val === "number" && val % 1 !== 0 && !formatFn,
  });
}

(function initStatObserver() {
  var statIds = ["stat-bus-pct", "stat-rail-pct", "stat-additional-pop", "stat-new-rail-pct", "stat-n-stations"];
  var visibleStats = {};

  // Prefetch data immediately
  cachedFetch(DATA_BASE + "coverage_stats.json")
    .then(function (stats) {
      _statDataReady.coverage = stats;
      Object.keys(visibleStats).forEach(tryAnimateStat);
    }).catch(function () {});

  cachedFetch(DATA_BASE + "counterfactual_stats.json")
    .then(function (stats) {
      _statDataReady.counterfactual = stats;
      Object.keys(visibleStats).forEach(tryAnimateStat);
    }).catch(function () {});

  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var id = entry.target.id;
      visibleStats[id] = true;
      observer.unobserve(entry.target);
      tryAnimateStat(id);
    });
  }, { threshold: 0.1 });

  statIds.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) observer.observe(el);
  });
})();

/* Shared: discrete legend */
function addLegend(svg, x, y, items, title) {
  var g = svg.append("g").attr("transform", "translate(" + x + "," + y + ")");
  if (title) g.append("text").attr("y", -8)
    .attr("font-family", "'Space Grotesk', sans-serif")
    .attr("font-size", "13px").attr("font-weight", 700).attr("fill", COLORS.text)
    .text(title);
  items.forEach(function (d, i) {
    var row = g.append("g").attr("transform", "translate(0," + (i * 20) + ")");
    row.append("rect").attr("width", 18).attr("height", 14)
      .attr("fill", d.color).attr("rx", 2).attr("opacity", d.opacity || 1);
    if (d.strokeColor) {
      row.append("rect").attr("width", 18).attr("height", 14)
        .attr("fill", "none").attr("rx", 2)
        .attr("stroke", d.strokeColor).attr("stroke-width", 2);
    }
    if (d.dashed) {
      row.append("rect").attr("width", 18).attr("height", 14)
        .attr("fill", "none").attr("rx", 2)
        .attr("stroke", d.dashed).attr("stroke-width", 1.5)
        .attr("stroke-dasharray", "3,2");
    }
    row.append("text").attr("x", 24).attr("y", 11)
      .attr("font-size", "12px").attr("fill", COLORS.text)
      .attr("font-family", "'DM Sans', sans-serif")
      .text(d.label);
  });
}

/* ========================================================================
   Shared: 9-class YlOrRd density color scale — original 8 bins + 35K+ peak
   ======================================================================== */
function makeDensityColorScale() {
  var colors = ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#800026"];
  var thresholds = [2000, 4000, 7000, 10000, 15000, 25000, 35000];
  return { scale: d3.scaleThreshold().domain(thresholds).range(colors), thresholds: thresholds, colors: colors };
}

/* ========================================================================
   Shared: aggregate hex properties by city/neighborhood name
   ======================================================================== */
function aggregateCities(props) {
  var byName = {};
  props.forEach(function (p) {
    if (!p.n) return;
    if (!byName[p.n]) byName[p.n] = { cx: 0, cy: 0, count: 0, pop: 0, d_max: 0, def_sum: 0, def_count: 0 };
    var a = byName[p.n];
    a.cx += p.cx; a.cy += p.cy; a.count += 1;
    a.pop += (p.pop || 0);
    a.d_max = Math.max(a.d_max, p.d || 0);
    if (p.def != null) { a.def_sum += p.def; a.def_count += 1; }
  });
  Object.keys(byName).forEach(function (name) {
    var a = byName[name];
    a.cx /= a.count; a.cy /= a.count;
    a.def_avg = a.def_count > 0 ? a.def_sum / a.def_count : null;
  });
  return byName;
}

/* ========================================================================
   Shared: place city labels with bounding-box collision avoidance
   ======================================================================== */
function placeLabels(svg, proj, cities, labelDefs, opts) {
  opts = opts || {};
  var pad = opts.padding || 4;
  var placed = [];

  labelDefs.forEach(function (lbl) {
    var city = cities[lbl.name];
    if (!city) return;
    var pt = proj([city.cx, city.cy]);
    if (!pt || pt[0] < 0 || pt[1] < 0) return;

    var x = pt[0] + (lbl.dx || 0);
    var y = pt[1] + (lbl.dy || 0);
    var sz = lbl.size || 10;
    var anchor = lbl.anchor || "middle";
    var approxW = lbl.name.length * sz * 0.58;
    var approxH = sz * 1.3;

    var bx;
    if (anchor === "end") bx = x - approxW;
    else if (anchor === "start") bx = x;
    else bx = x - approxW / 2;

    var bbox = { x: bx - pad, y: y - approxH - pad, w: approxW + pad * 2, h: approxH + pad * 2 };

    var collision = placed.some(function (p) {
      return !(bbox.x + bbox.w < p.x || bbox.x > p.x + p.w ||
               bbox.y + bbox.h < p.y || bbox.y > p.y + p.h);
    });
    if (collision) return;
    placed.push(bbox);

    var fill = lbl.color || "#222";
    var stroke = lbl.stroke || "white";

    // Optional colored indicator dot
    if (lbl.dot) {
      svg.append("circle")
        .attr("cx", x + (anchor === "end" ? 6 : anchor === "start" ? -6 : 0))
        .attr("cy", y - sz * 0.35)
        .attr("r", 3.5)
        .attr("fill", lbl.dot)
        .attr("stroke", "white").attr("stroke-width", 1)
        .style("pointer-events", "none");
    }

    svg.append("text")
      .attr("x", x).attr("y", y)
      .attr("text-anchor", anchor)
      .attr("font-size", sz + "px").attr("font-weight", 700)
      .attr("font-family", "'DM Sans', sans-serif")
      .attr("fill", fill)
      .attr("stroke", stroke).attr("stroke-width", 2.5)
      .attr("paint-order", "stroke")
      .style("pointer-events", "none")
      .text(lbl.name);
  });
}

/* Curated hero labels — major cities across LA County, manually offset to avoid overlap */
var HERO_LABELS = [
  { name: "Downtown", dx: 0, dy: 18, anchor: "middle", size: 12 },
  { name: "Long Beach", dx: 0, dy: -8, anchor: "middle", size: 12 },
  { name: "Pasadena", dx: 14, dy: 0, anchor: "start", size: 12 },
  { name: "Santa Monica", dx: -10, dy: 4, anchor: "end", size: 12 },
  { name: "Burbank", dx: -14, dy: -4, anchor: "end", size: 11 },
  { name: "Glendale", dx: 14, dy: 6, anchor: "start", size: 11 },
  { name: "Pomona", dx: 10, dy: 0, anchor: "start", size: 12 },
  { name: "Lancaster", dx: 0, dy: -8, anchor: "middle", size: 12 },
  { name: "Palmdale", dx: 0, dy: 12, anchor: "middle", size: 12 },
  { name: "Santa Clarita", dx: 0, dy: -8, anchor: "middle", size: 12 },
  { name: "Torrance", dx: -12, dy: 4, anchor: "end", size: 11 },
  { name: "Hollywood", dx: 0, dy: -12, anchor: "middle", size: 10 },
  { name: "Koreatown", dx: -22, dy: 0, anchor: "end", size: 10 },
  { name: "Inglewood", dx: -14, dy: 10, anchor: "end", size: 10 },
  { name: "Compton", dx: 14, dy: 4, anchor: "start", size: 10 },
  { name: "East Los Angeles", dx: 14, dy: -4, anchor: "start", size: 10 },
  { name: "Whittier", dx: 10, dy: 0, anchor: "start", size: 10 },
  { name: "El Monte", dx: 0, dy: -10, anchor: "middle", size: 10 },
  { name: "San Pedro", dx: 0, dy: 10, anchor: "middle", size: 10 },
  { name: "Beverly Hills", dx: -14, dy: -10, anchor: "end", size: 10 },
  { name: "West Covina", dx: 10, dy: 0, anchor: "start", size: 10 },
  { name: "Malibu", dx: -10, dy: 0, anchor: "end", size: 10 },
];

/* Compact geographic labels for smaller maps (coverage, counterfactual) */
var GEO_LABELS = [
  { name: "Downtown", dx: 0, dy: 14, anchor: "middle", size: 10 },
  { name: "Long Beach", dx: 0, dy: -6, anchor: "middle", size: 10 },
  { name: "Pasadena", dx: 10, dy: 0, anchor: "start", size: 10 },
  { name: "Santa Monica", dx: -8, dy: 0, anchor: "end", size: 10 },
  { name: "Burbank", dx: -10, dy: -4, anchor: "end", size: 9 },
  { name: "Glendale", dx: 10, dy: 4, anchor: "start", size: 9 },
  { name: "Pomona", dx: 8, dy: 0, anchor: "start", size: 9 },
  { name: "Lancaster", dx: 0, dy: -6, anchor: "middle", size: 9 },
  { name: "Hollywood", dx: 0, dy: -10, anchor: "middle", size: 9 },
  { name: "Inglewood", dx: -10, dy: 6, anchor: "end", size: 9 },
  { name: "Torrance", dx: -10, dy: 4, anchor: "end", size: 9 },
  { name: "Compton", dx: 10, dy: 4, anchor: "start", size: 9 },
];


// ======================================================================
// Section 1: Hero — Hex density choropleth (8-bin + curated labels)
// ======================================================================
window.VIZ.heroDensity = function () {
  if (!document.getElementById("viz-hero")) return;
  console.log("heroDensity: starting");

  Promise.all([
    cachedFetch(DATA_BASE + "hex_grid.topojson"),
    cachedFetch(DATA_BASE + "hex_props.json"),
    cachedFetch(DATA_BASE + "county_boundary.geojson"),
  ]).then(function (results) {
    var topo = results[0], props = results[1], boundary = results[2];
    var r = makeSvg("#viz-hero", 0.65);
    var proj = fitProjection(boundary, r.w, r.h, 30);
    var pathGen = d3.geoPath().projection(proj);

    var propsMap = {};
    props.forEach(function (p) { propsMap[p.id] = p; });

    var objKey = Object.keys(topo.objects)[0];
    var hexFeatures = topojson.feature(topo, topo.objects[objKey]).features;

    // Continuous YlOrRd density scale (sqrt domain)
    var ds = makeDensityColorScale(props);

    var zoomGroup = r.svg.append("g").attr("class", "map-zoom-group");

    // County outline
    zoomGroup.selectAll(".county")
      .data(boundary.features)
      .join("path").attr("d", pathGen)
      .attr("fill", "none").attr("stroke", "#bbb").attr("stroke-width", 0.75);

    // Hex cells
    var hexGroup = zoomGroup.append("g");
    hexGroup.selectAll(".hex")
      .data(hexFeatures)
      .join("path")
      .attr("class", "hex")
      .attr("d", pathGen)
      .attr("fill", function (d) {
        var p = propsMap[d.properties.hex_id];
        return (p && p.d > 0) ? ds.scale(p.d) : "#E0E4E8";
      })
      .attr("stroke", "rgba(255,255,255,0.3)")
      .attr("stroke-width", 0.4);

    // Legend
    var prev = 0;
    var legendItems = ds.thresholds.map(function (t, i) {
      var item = { color: ds.colors[i], label: fmtRange(Math.round(prev), Math.round(t)) };
      prev = t;
      return item;
    });
    legendItems.push({ color: ds.colors[ds.colors.length - 1], label: fmtRange(Math.round(prev), null) });
    addLegend(r.svg, 16, r.h - (legendItems.length * 20 + 24), legendItems, "Population Density");

    // Curated city labels with collision avoidance
    var cities = aggregateCities(props);
    placeLabels(zoomGroup, proj, cities, HERO_LABELS);

    // Tooltip
    var tooltip = d3.select("#viz-hero").append("div")
      .attr("class", "hex-tooltip").style("opacity", 0);
    var lastHovered = null;
    hexGroup.on("mouseover", function (event) {
      var target = event.target;
      if (target === lastHovered) return;
      if (lastHovered) d3.select(lastHovered).attr("stroke-width", 0.4).attr("stroke", "rgba(255,255,255,0.3)");
      var sel = d3.select(target);
      if (!sel.classed("hex")) { tooltip.style("opacity", 0); lastHovered = null; return; }
      lastHovered = target;
      sel.attr("stroke-width", 1.5).attr("stroke", "#333");
      var d = sel.datum();
      var p = d ? propsMap[d.properties.hex_id] : null;
      if (!p || p.d <= 0) return;
      var rect = d3.select("#viz-hero").node().getBoundingClientRect();
      tooltip.html(
        "<strong>" + (p.n || "\u2014") + "</strong><br>" +
        "Density: " + fmt(p.d) + "/mi\u00B2<br>" +
        "Population: " + fmt(p.pop)
      )
      .style("left", (event.clientX - rect.left + 12) + "px")
      .style("top",  (event.clientY - rect.top  - 30) + "px")
      .style("opacity", 1);
    }).on("mouseleave", function () {
      if (lastHovered) d3.select(lastHovered).attr("stroke-width", 0.4).attr("stroke", "rgba(255,255,255,0.3)");
      lastHovered = null;
      tooltip.style("opacity", 0);
    });

    // Zoom/pan (ctrl+scroll to zoom, drag to pan; plain scroll passes through)
    var heroLabels = zoomGroup.selectAll("text, circle").filter(function () {
      return d3.select(this).style("pointer-events") === "none";
    });
    r.svg.classed("map-zoomable", true)
      .call(d3.zoom()
        .scaleExtent([1, 8])
        .filter(function (event) {
          return !event.type.startsWith("wheel") || event.ctrlKey;
        })
        .on("zoom", function (event) {
          zoomGroup.attr("transform", event.transform);
          var k = event.transform.k;
          var labelOpacity = k < 2 ? 1 : Math.max(0, 1 - (k - 2) / 2);
          heroLabels.style("opacity", labelOpacity);
        }));

  }).catch(function (err) { console.error("Hero density viz error:", err); });
};


// ======================================================================
// Section 2: Coverage — Density background + transit coverage overlay
// ======================================================================
window.VIZ.coverage = function () {
  console.log("coverage: starting");
  Promise.all([
    cachedFetch(DATA_BASE + "hex_grid.topojson"),
    cachedFetch(DATA_BASE + "hex_props.json"),
    cachedFetch(DATA_BASE + "county_boundary.geojson"),
    fetch(DATA_BASE + "coverage_stats.json" + DATA_V).then(function (r) { return r.json(); }),
  ]).then(function (results) {
    var topo = results[0], props = results[1], boundary = results[2], stats = results[3];
    console.log("coverage: data loaded", props.length, "hex props");

    // Stats are now animated by the scroll-triggered stat observer system

    var propsMap = {};
    props.forEach(function (p) { propsMap[p.id] = p; });
    var objKey = Object.keys(topo.objects)[0];
    var hexFeatures = topojson.feature(topo, topo.objects[objKey]).features;
    var ds = makeDensityColorScale(props);
    var cities = aggregateCities(props);

    [
      { id: "#viz-coverage-bus", field: "bs", color: COLORS.bus, title: "Bus Coverage (\u00BC mi walk)", label: "Within \u00BC mi of bus stop" },
      { id: "#viz-coverage-rail", field: "rs", color: COLORS.rail, title: "Rail Coverage (\u00BD mi walk)", label: "Within \u00BD mi of rail station" },
    ].forEach(function (cfg) {
      var r = makeSvg(cfg.id, 0.9);
      var proj = fitProjection(boundary, r.w, r.h, 15);
      var pathGen = d3.geoPath().projection(proj);

      var zoomGroup = r.svg.append("g").attr("class", "map-zoom-group");

      // County outline
      zoomGroup.selectAll(".county")
        .data(boundary.features)
        .join("path").attr("d", pathGen)
        .attr("fill", "none").attr("stroke", "#bbb").attr("stroke-width", 0.75);

      // Hex cells — density colored background with coverage overlay
      zoomGroup.append("g").selectAll(".hex")
        .data(hexFeatures)
        .join("path")
        .attr("d", pathGen)
        .attr("fill", function (d) {
          var p = propsMap[d.properties.hex_id];
          if (!p || p.d <= 0) return "#E0E4E8";
          return ds.scale(p.d);
        })
        .attr("opacity", function (d) {
          var p = propsMap[d.properties.hex_id];
          return (p && p[cfg.field] > 0) ? 0.85 : 0.25;
        })
        .attr("stroke", function (d) {
          var p = propsMap[d.properties.hex_id];
          return (p && p[cfg.field] > 0) ? cfg.color : "rgba(255,255,255,0.2)";
        })
        .attr("stroke-width", function (d) {
          var p = propsMap[d.properties.hex_id];
          return (p && p[cfg.field] > 0) ? 1.5 : 0.3;
        });

      // Transparent hit-target layer (topmost, captures all hover events)
      var hitGroup = zoomGroup.append("g");
      hitGroup.selectAll(".hex")
        .data(hexFeatures).join("path")
        .attr("class", "hex").attr("d", pathGen)
        .attr("fill", "transparent").attr("stroke", "none").attr("pointer-events", "all");

      // Title
      r.svg.append("text").attr("x", r.w / 2).attr("y", 22)
        .attr("text-anchor", "middle")
        .attr("font-family", "'Space Grotesk', sans-serif")
        .attr("font-size", "16px").attr("font-weight", 700).attr("fill", COLORS.text)
        .text(cfg.title);

      // Legend
      addLegend(r.svg, 16, r.h - 60, [
        { color: "#feb24c", label: cfg.label, strokeColor: cfg.color },
        { color: "#E0E4E8", label: "Not covered", opacity: 0.5 },
      ], null);

      // City labels for geographic context
      placeLabels(zoomGroup, proj, cities, GEO_LABELS);

      // Tooltip
      var containerId = cfg.id;
      var tooltip = d3.select(containerId).append("div")
        .attr("class", "hex-tooltip").style("opacity", 0);
      var lastHovered = null;
      hitGroup.on("mouseover", function (event) {
        var target = event.target;
        if (target === lastHovered) return;
        if (lastHovered) d3.select(lastHovered).attr("opacity", 0);
        var sel = d3.select(target);
        if (!sel.classed("hex")) { tooltip.style("opacity", 0); lastHovered = null; return; }
        lastHovered = target;
        var d = sel.datum();
        var p = d ? propsMap[d.properties.hex_id] : null;
        if (!p || p.d <= 0) { tooltip.style("opacity", 0); return; }
        var rect = d3.select(containerId).node().getBoundingClientRect();
        var covered = p[cfg.field] > 0;
        var coverageLabel = cfg.field === "bs"
          ? (covered ? "Bus: Within \u00BC mi \u2713" : "Bus: Not covered")
          : (covered ? "Rail: Within \u00BD mi \u2713" : "Rail: Not covered");
        tooltip.html(
          "<strong>" + (p.n || "\u2014") + "</strong><br>" +
          "Density: " + fmt(p.d) + "/mi\u00B2<br>" +
          coverageLabel
        )
        .style("left", (event.clientX - rect.left + 12) + "px")
        .style("top",  (event.clientY - rect.top  - 30) + "px")
        .style("opacity", 1);
      }).on("mouseleave", function () {
        if (lastHovered) d3.select(lastHovered).attr("opacity", 0);
        lastHovered = null;
        tooltip.style("opacity", 0);
      });

      // Zoom/pan
      var covLabels = zoomGroup.selectAll("text, circle").filter(function () {
        return d3.select(this).style("pointer-events") === "none";
      });
      r.svg.classed("map-zoomable", true)
        .call(d3.zoom()
          .scaleExtent([1, 8])
          .filter(function (event) {
            return !event.type.startsWith("wheel") || event.ctrlKey;
          })
          .on("zoom", function (event) {
            zoomGroup.attr("transform", event.transform);
            var k = event.transform.k;
            var labelOpacity = k < 2 ? 1 : Math.max(0, 1 - (k - 2) / 2);
            covLabels.style("opacity", labelOpacity);
          }));
    });
  }).catch(function (err) { console.error("Coverage viz error:", err); });
};


// ======================================================================
// Section 3: Transit Deserts — Hex choropleth with dual-type labels
// ======================================================================
window.VIZ.deserts = function () {
  console.log("deserts: starting");
  var containerId = "#viz-deserts";

  Promise.all([
    fetch(DATA_BASE + "hex_grid.topojson" + DATA_V).then(function (r) { return r.json(); }),
    cachedFetch(DATA_BASE + "hex_props.json"),
    cachedFetch(DATA_BASE + "county_boundary.geojson"),
  ]).then(function (results) {
    console.log("deserts: data loaded");
    var topo = results[0], props = results[1], boundary = results[2];
    var r = makeSvg(containerId, 0.65);
    var proj = fitProjection(boundary, r.w, r.h, 30);
    var pathGen = d3.geoPath().projection(proj);

    var propsMap = {};
    props.forEach(function (p) { propsMap[p.id] = p; });

    var objKey = Object.keys(topo.objects)[0];
    var hexFeatures = topojson.feature(topo, topo.objects[objKey]).features;

    var zoomGroup = r.svg.append("g").attr("class", "map-zoom-group");

    // County outline
    zoomGroup.selectAll(".county")
      .data(boundary.features)
      .join("path").attr("d", pathGen)
      .attr("fill", "none").attr("stroke", "#999").attr("stroke-width", 0.5);

    // Deficit color scale
    var deficits = props.map(function (p) { return p.def; }).filter(function (d) { return d != null; });
    var absMax = d3.quantile(deficits.map(Math.abs).sort(d3.ascending), 0.95) || 2;
    var colorScale = d3.scaleDiverging()
      .domain([-absMax, 0, absMax])
      .interpolator(d3.interpolateRdYlBu)
      .clamp(true);

    // Tooltip
    var tooltip = d3.select(containerId).append("div")
      .attr("class", "hex-tooltip")
      .style("position", "absolute").style("opacity", 0);

    // Draw hexes
    var hexGroup = zoomGroup.append("g").attr("class", "hex-group");
    hexGroup.selectAll(".hex")
      .data(hexFeatures)
      .join("path")
      .attr("class", "hex")
      .attr("d", pathGen)
      .attr("fill", function (d) {
        var p = propsMap[d.properties.hex_id];
        if (!p || p.def == null) return "#ccc";
        return colorScale(p.def);
      })
      .attr("stroke", "#888")
      .attr("stroke-width", 0.3)
      .attr("opacity", 0.85);

    // Event delegation for hover
    var lastHovered = null;
    hexGroup.on("mouseover", function (event) {
      var target = event.target;
      if (target === lastHovered) return;
      if (lastHovered) d3.select(lastHovered).attr("stroke-width", 0.3).attr("stroke", "#888");
      var sel = d3.select(target);
      if (!sel.classed("hex")) { tooltip.style("opacity", 0); lastHovered = null; return; }
      lastHovered = target;
      sel.attr("stroke-width", 1.5).attr("stroke", "#333");
      var d = sel.datum();
      var p = d ? propsMap[d.properties.hex_id] : null;
      if (!p) return;
      var rect = d3.select(containerId).node().getBoundingClientRect();
      tooltip.html(
        "<strong>" + (p.n || "\u2014") + "</strong><br>" +
        "Density: " + fmt(p.d) + "/mi\u00B2<br>" +
        "Access score: " + p.as + "<br>" +
        "Deficit: " + (p.def != null ? p.def.toFixed(2) : "\u2014")
      )
      .style("left", (event.clientX - rect.left + 12) + "px")
      .style("top",  (event.clientY - rect.top  - 30) + "px")
      .style("opacity", 1);
    }).on("mouseleave", function () {
      if (lastHovered) d3.select(lastHovered).attr("stroke-width", 0.3).attr("stroke", "#888");
      lastHovered = null;
      tooltip.style("opacity", 0);
    });

    // Legend
    addLegend(r.svg, 16, r.h - 130, [
      { color: "#d73027", label: "Transit desert" },
      { color: "#fdae61", label: "Underserved" },
      { color: "#fee090", label: "At expected" },
      { color: "#abd9e9", label: "Above expected" },
      { color: "#4575b4", label: "Well-served" },
    ], "Transit Access vs. Density");

    // Data-driven labels: top desert + top well-served neighborhoods
    var cities = aggregateCities(props);
    var desertEntries = [];
    var wellServedEntries = [];
    Object.entries(cities).forEach(function (e) {
      var name = e[0], c = e[1];
      if (c.def_avg == null || c.count < 3) return;
      desertEntries.push({ name: name, def: c.def_avg, pop: c.pop });
      wellServedEntries.push({ name: name, def: c.def_avg, pop: c.pop });
    });

    // Worst deserts (most negative deficit, high pop preferred)
    desertEntries.sort(function (a, b) { return a.def - b.def; });
    var desertLabels = [];
    var seen = {};
    desertEntries.slice(0, 12).forEach(function (e) {
      if (seen[e.name] || desertLabels.length >= 6) return;
      seen[e.name] = true;
      desertLabels.push({
        name: e.name, size: 10, anchor: "start", dx: 10, dy: 0,
        color: "#b71c1c", stroke: "white", dot: "#d73027"
      });
    });

    // Best served (most positive deficit, high pop preferred)
    wellServedEntries.sort(function (a, b) { return b.def - a.def; });
    var wellLabels = [];
    wellServedEntries.slice(0, 12).forEach(function (e) {
      if (seen[e.name] || wellLabels.length >= 5) return;
      seen[e.name] = true;
      wellLabels.push({
        name: e.name, size: 10, anchor: "end", dx: -10, dy: 0,
        color: "#1a237e", stroke: "white", dot: "#4575b4"
      });
    });

    placeLabels(zoomGroup, proj, cities, desertLabels.concat(wellLabels));

    // Bar chart inset
    buildDesertBars(props);

    // Zoom/pan
    var desertLabelsEl = zoomGroup.selectAll("text, circle").filter(function () {
      return d3.select(this).style("pointer-events") === "none";
    });
    r.svg.classed("map-zoomable", true)
      .call(d3.zoom()
        .scaleExtent([1, 8])
        .filter(function (event) {
          return !event.type.startsWith("wheel") || event.ctrlKey;
        })
        .on("zoom", function (event) {
          zoomGroup.attr("transform", event.transform);
          var k = event.transform.k;
          var labelOpacity = k < 2 ? 1 : Math.max(0, 1 - (k - 2) / 2);
          desertLabelsEl.style("opacity", labelOpacity);
        }));

  }).catch(function (err) { console.error("Deserts viz error:", err); });
};

function buildDesertBars(props) {
  var container = d3.select("#viz-desert-bars");
  if (container.empty()) return;

  var byHood = {};
  props.forEach(function (p) {
    if (p.n && p.def != null) {
      if (!byHood[p.n]) byHood[p.n] = [];
      byHood[p.n].push(p.def);
    }
  });

  var ranked = Object.entries(byHood)
    .map(function (e) { return { name: e[0], avg: d3.mean(e[1]), count: e[1].length }; })
    .filter(function (d) { return d.count >= 3; })
    .sort(function (a, b) { return a.avg - b.avg; })
    .slice(0, 10);

  if (!ranked.length) return;

  var margin = { top: 32, right: 20, bottom: 10, left: 150 };
  var barH = 26;
  var w = container.node().getBoundingClientRect().width || 600;
  var h = margin.top + margin.bottom + ranked.length * barH;

  var svg = container.append("svg").attr("viewBox", "0 0 " + w + " " + h);

  svg.append("text").attr("x", margin.left).attr("y", 20)
    .attr("font-family", "'Space Grotesk', sans-serif")
    .attr("font-size", "15px").attr("font-weight", 700).attr("fill", COLORS.text)
    .text("Top 10 Transit Desert Neighborhoods");

  var x = d3.scaleLinear()
    .domain([d3.min(ranked, function (d) { return d.avg; }), 0])
    .range([margin.left, w - margin.right]);

  var y = d3.scaleBand()
    .domain(ranked.map(function (d) { return d.name; }))
    .range([margin.top, h - margin.bottom])
    .padding(0.25);

  svg.selectAll(".bar").data(ranked).join("rect")
    .attr("x", x(0))
    .attr("y", function (d) { return y(d.name); })
    .attr("width", 0)
    .attr("height", y.bandwidth())
    .attr("fill", "#d73027").attr("rx", 3)
    .transition()
    .delay(function (d, i) { return i * 80; })
    .duration(600)
    .ease(d3.easeQuadOut)
    .attr("x", function (d) { return x(d.avg); })
    .attr("width", function (d) { return x(0) - x(d.avg); });

  svg.selectAll(".label").data(ranked).join("text")
    .attr("x", margin.left - 6)
    .attr("y", function (d) { return y(d.name) + y.bandwidth() / 2; })
    .attr("dy", "0.35em").attr("text-anchor", "end")
    .attr("font-size", "12px").attr("fill", COLORS.text)
    .attr("font-family", "'DM Sans', sans-serif")
    .attr("opacity", 0)
    .text(function (d) { return d.name; })
    .transition()
    .delay(function (d, i) { return i * 80; })
    .duration(400)
    .attr("opacity", 1);
}


// ======================================================================
// Section 5: Counterfactual — Density background + rail coverage overlay
// ======================================================================
window.VIZ.counterfactual = function () {
  console.log("counterfactual: starting");
  Promise.all([
    fetch(DATA_BASE + "counterfactual_stations.geojson" + DATA_V).then(function (r) { return r.json(); }),
    fetch(DATA_BASE + "counterfactual_stats.json" + DATA_V).then(function (r) { return r.json(); }),
    cachedFetch(DATA_BASE + "hex_props.json"),
    cachedFetch(DATA_BASE + "county_boundary.geojson"),
    cachedFetch(DATA_BASE + "hex_grid.topojson"),
    fetch(DATA_BASE + "rail_stations.json" + DATA_V).then(function (r) { return r.json(); }),
    fetch(DATA_BASE + "brt_stations.json" + DATA_V).then(function (r) { return r.json(); }),
  ]).then(function (results) {
    console.log("counterfactual: data loaded");
    var stations = results[0], stats = results[1], hexProps = results[2], boundary = results[3], topo = results[4], railCoords = results[5], brtCoords = results[6];

    // Stats are now animated by the scroll-triggered stat observer system

    // Precompute rail coverage using same 1km distance check for both existing and new stations
    var KM1 = 0.009;  // ~1km in degrees at LA latitude
    function withinKm1(cx, cy, sx, sy) {
      var dlat = cy - sy;
      var dlng = (cx - sx) * Math.cos((cy + sy) / 2 * Math.PI / 180);
      return (dlat * dlat + dlng * dlng) < KM1 * KM1;
    }

    // Existing rail coverage (from actual station coordinates)
    var existingCoverageSet = {};
    hexProps.forEach(function (p) {
      for (var i = 0; i < railCoords.length; i++) {
        if (withinKm1(p.cx, p.cy, railCoords[i][0], railCoords[i][1])) {
          existingCoverageSet[p.id] = true; break;
        }
      }
    });

    // BRT coverage (J Line + G Line, 1km)
    var brtCoverageSet = {};
    hexProps.forEach(function (p) {
      if (existingCoverageSet[p.id]) return;
      for (var i = 0; i < brtCoords.length; i++) {
        if (withinKm1(p.cx, p.cy, brtCoords[i][0], brtCoords[i][1])) {
          brtCoverageSet[p.id] = true; break;
        }
      }
    });

    // New station coverage (D Line + hypothetical)
    var stationCoords = stations.features.map(function (f) { return f.geometry.coordinates; });
    var newCoverageSet = {};
    hexProps.forEach(function (p) {
      if (existingCoverageSet[p.id] || brtCoverageSet[p.id]) return;
      for (var i = 0; i < stationCoords.length; i++) {
        if (withinKm1(p.cx, p.cy, stationCoords[i][0], stationCoords[i][1])) {
          newCoverageSet[p.id] = true; break;
        }
      }
    });

    var propsMap = {};
    hexProps.forEach(function (p) { propsMap[p.id] = p; });
    var objKey = Object.keys(topo.objects)[0];
    var hexFeatures = topojson.feature(topo, topo.objects[objKey]).features;
    var ds = makeDensityColorScale(hexProps);
    var cities = aggregateCities(hexProps);

    var containerId = "#viz-counterfactual";
    var r = makeSvg(containerId, 0.65);
    var proj = fitProjection(boundary, r.w, r.h, 30);
    var pathGen = d3.geoPath().projection(proj);

    var zoomGroup = r.svg.append("g").attr("class", "map-zoom-group");

    // County outline
    zoomGroup.selectAll(".county")
      .data(boundary.features)
      .join("path").attr("d", pathGen)
      .attr("fill", "none").attr("stroke", "#bbb").attr("stroke-width", 0.75);

    // Base layer: all hexes colored by density (muted)
    zoomGroup.append("g").selectAll(".hex-base")
      .data(hexFeatures)
      .join("path")
      .attr("d", pathGen)
      .attr("fill", function (d) {
        var p = propsMap[d.properties.hex_id];
        if (!p || p.d <= 0) return "#E0E4E8";
        return ds.scale(p.d);
      })
      .attr("opacity", 0.35)
      .attr("stroke", "rgba(255,255,255,0.15)")
      .attr("stroke-width", 0.3);

    // Overlay layer: existing rail coverage (1km) — solid hex fill
    zoomGroup.append("g").selectAll(".hex-rail")
      .data(hexFeatures.filter(function (d) {
        var p = propsMap[d.properties.hex_id];
        return p && existingCoverageSet[p.id];
      }))
      .join("path")
      .attr("d", pathGen)
      .attr("fill", "#4575b4")
      .attr("opacity", 0.6)
      .attr("stroke", "#2c5985")
      .attr("stroke-width", 1);

    // BRT coverage layer (J Line + G Line) — distinct teal
    zoomGroup.append("g").selectAll(".hex-brt")
      .data(hexFeatures.filter(function (d) {
        var p = propsMap[d.properties.hex_id];
        return p && brtCoverageSet[p.id];
      }))
      .join("path")
      .attr("d", pathGen)
      .attr("fill", "#2a9d8f")
      .attr("opacity", 0.5)
      .attr("stroke", "#1a7a6f")
      .attr("stroke-width", 0.8);

    // Hypothetical/D Line coverage — soft radial gradient circles
    var defs = r.svg.append("defs");
    defs.append("radialGradient").attr("id", "grad-cf-hypo")
      .selectAll("stop").data([
        {offset: "0%", color: "#d73027", opacity: 0.30},
        {offset: "65%", color: "#d73027", opacity: 0.13},
        {offset: "100%", color: "#d73027", opacity: 0}
      ]).join("stop")
      .attr("offset", function(d) { return d.offset; })
      .attr("stop-color", function(d) { return d.color; })
      .attr("stop-opacity", function(d) { return d.opacity; });

    defs.append("radialGradient").attr("id", "grad-cf-dline")
      .selectAll("stop").data([
        {offset: "0%", color: "#7b68ee", opacity: 0.30},
        {offset: "65%", color: "#7b68ee", opacity: 0.13},
        {offset: "100%", color: "#7b68ee", opacity: 0}
      ]).join("stop")
      .attr("offset", function(d) { return d.offset; })
      .attr("stop-color", function(d) { return d.color; })
      .attr("stop-opacity", function(d) { return d.opacity; });

    // Compute 1km in projected pixels (reference point at LA latitude)
    var refPt = proj([-118.25, 34.05]);
    var refPtN = proj([-118.25, 34.05 + 0.009]);
    var km1px = Math.abs(refPtN[1] - refPt[1]);

    var coverageGroup = zoomGroup.append("g").attr("class", "coverage-circles");
    stations.features.forEach(function (f) {
      var pt = proj(f.geometry.coordinates);
      if (!pt) return;
      var isDLine = (f.properties.station_type || "").indexOf("d_line") === 0;
      coverageGroup.append("circle")
        .attr("cx", pt[0]).attr("cy", pt[1])
        .attr("r", km1px)
        .attr("fill", isDLine ? "url(#grad-cf-dline)" : "url(#grad-cf-hypo)")
        .style("pointer-events", "none");
    });

    // Transparent hit-target layer for hex hover (below station markers)
    var hitGroup = zoomGroup.append("g");
    hitGroup.selectAll(".hex").data(hexFeatures).join("path")
      .attr("class", "hex").attr("d", pathGen)
      .attr("fill", "transparent").attr("stroke", "none");

    // Station markers (on top of hex hit layer so they capture hover)
    var markerGroup = zoomGroup.append("g").attr("class", "station-markers");
    // Find nearest neighborhood for each station
    function nearestNeighborhood(lng, lat) {
      var best = null, bestDist = Infinity;
      hexProps.forEach(function (p) {
        if (!p.n) return;
        var d = (p.cx - lng) * (p.cx - lng) + (p.cy - lat) * (p.cy - lat);
        if (d < bestDist) { bestDist = d; best = p.n; }
      });
      return best;
    }
    stations.features.forEach(function (f) {
      var pt = proj(f.geometry.coordinates);
      if (!pt) return;
      var props = f.properties;
      var isDLine = (props.station_type || "").indexOf("d_line") === 0;
      var color = isDLine ? "#7b68ee" : "#d73027";
      // Outer ring (decorative)
      markerGroup.append("circle")
        .attr("cx", pt[0]).attr("cy", pt[1]).attr("r", 8)
        .attr("fill", "none").attr("stroke", color).attr("stroke-width", 1.5)
        .attr("stroke-dasharray", "3,2").attr("opacity", 0.6)
        .style("pointer-events", "none");
      // Inner dot (decorative)
      markerGroup.append("circle")
        .attr("cx", pt[0]).attr("cy", pt[1]).attr("r", 4)
        .attr("fill", color).attr("stroke", "white").attr("stroke-width", 1.5)
        .style("pointer-events", "none");
      // Invisible larger hit target
      var hood = props.name || nearestNeighborhood(f.geometry.coordinates[0], f.geometry.coordinates[1]);
      markerGroup.append("circle")
        .attr("cx", pt[0]).attr("cy", pt[1]).attr("r", 12)
        .attr("fill", "transparent").attr("stroke", "none")
        .style("cursor", "pointer")
        .datum({ props: props, isDLine: isDLine, hood: hood });
    });

    // Legend
    addLegend(r.svg, 16, r.h - 130, [
      { color: "#4575b4", label: "Existing rail coverage (1 km)" },
      { color: "#2a9d8f", label: "BRT coverage \u2014 J/G Line (1 km)" },
      { color: "#7b68ee", label: "D Line extension (2025\u20132027)", opacity: 0.5 },
      { color: "#d73027", label: "Hypothetical station + 1 km reach", opacity: 0.4 },
      { color: "#feb24c", label: "Population density (background)", opacity: 0.5 },
    ], "Counterfactual Rail Expansion");

    // City labels for geographic context
    placeLabels(zoomGroup, proj, cities, GEO_LABELS);

    // Tooltip
    var tooltip = d3.select(containerId).append("div")
      .attr("class", "hex-tooltip").style("opacity", 0);

    // Station marker hover
    markerGroup.on("mouseover", function (event) {
      var sel = d3.select(event.target);
      var d = sel.datum();
      if (!d) return;
      var rect = d3.select(containerId).node().getBoundingClientRect();
      var p = d.props;
      var lines;
      if (d.isDLine) {
        lines = "<strong>" + (p.name || "D Line Station") + "</strong><br>" +
          "D Line Section " + (p.station_type || "").replace("d_line_section_", "") +
          "<br>Opening 2025\u20132027";
      } else {
        lines = "<strong>Priority #" + p.station_number + "</strong><br>" +
          (d.hood ? d.hood + "<br>" : "") +
          "Covers " + fmt(p.population_covered) + " residents<br>" +
          "Cumulative: " + fmt(p.cumulative_coverage);
      }
      tooltip.html(lines)
        .style("left", (event.clientX - rect.left + 12) + "px")
        .style("top",  (event.clientY - rect.top  - 30) + "px")
        .style("opacity", 1);
    }).on("mouseleave", function () {
      tooltip.style("opacity", 0);
    });

    // Hex hover
    var lastHovered = null;
    hitGroup.on("mouseover", function (event) {
      var target = event.target;
      if (target === lastHovered) return;
      if (lastHovered) d3.select(lastHovered).attr("opacity", 0);
      var sel = d3.select(target);
      if (!sel.classed("hex")) { tooltip.style("opacity", 0); lastHovered = null; return; }
      lastHovered = target;
      var d = sel.datum();
      var p = d ? propsMap[d.properties.hex_id] : null;
      if (!p || p.d <= 0) { tooltip.style("opacity", 0); return; }
      var rect = d3.select(containerId).node().getBoundingClientRect();
      var status = existingCoverageSet[p.id]
        ? "Rail: Existing \u2713"
        : brtCoverageSet[p.id] ? "BRT: J/G Line \u2713"
        : newCoverageSet[p.id] ? "Rail: New coverage \u2713" : "Rapid transit: Not covered";
      tooltip.html(
        "<strong>" + (p.n || "\u2014") + "</strong><br>" +
        "Density: " + fmt(p.d) + "/mi\u00B2<br>" +
        status
      )
      .style("left", (event.clientX - rect.left + 12) + "px")
      .style("top",  (event.clientY - rect.top  - 30) + "px")
      .style("opacity", 1);
    }).on("mouseleave", function () {
      if (lastHovered) d3.select(lastHovered).attr("opacity", 0);
      lastHovered = null;
      tooltip.style("opacity", 0);
    });

    // Zoom/pan — scale markers inversely, fade labels when zoomed in
    var labelEls = zoomGroup.selectAll("text, circle").filter(function () {
      return d3.select(this).style("pointer-events") === "none";
    });
    r.svg.classed("map-zoomable", true)
      .call(d3.zoom()
        .scaleExtent([1, 12])
        .filter(function (event) {
          return !event.type.startsWith("wheel") || event.ctrlKey;
        })
        .on("zoom", function (event) {
          zoomGroup.attr("transform", event.transform);
          var k = event.transform.k;
          markerGroup.selectAll("circle").each(function () {
            var el = d3.select(this);
            var baseR = el.attr("fill") === "none" ? 8 : 4;
            var baseSW = 1.5;
            el.attr("r", baseR / k).attr("stroke-width", baseSW / k);
          });
          // Fade labels when zoomed past 2×
          var labelOpacity = k < 2 ? 1 : Math.max(0, 1 - (k - 2) / 2);
          labelEls.style("opacity", labelOpacity);
        }));

  }).catch(function (err) { console.error("Counterfactual viz error:", err); });
};


// Stat counters are now handled by the scroll-triggered animation system
// defined above (initStatObserver IIFE). Data is prefetched immediately;
// counters animate when they scroll into view.
