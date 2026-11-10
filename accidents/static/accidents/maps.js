/*
 * Shared map helper (Leaflet).
 *  - Background tiles: Esri World Street Map, with Esri World Imagery
 *    (satellite) selectable in the layer control.
 *    NOT used: tile.openstreetmap.org (usage policy answers with an "Access
 *    blocked" picture) and CARTO basemaps (now an "API KEY REQUIRED" picture).
 *    Both return a normal image, so no error-based fallback can detect them.
 *  - Region and district boundaries drawn from local files, so the map still
 *    shows Ghana when background tiles cannot load (offline, blocked network).
 *  - districtAt(lat, lng): which district a GPS point falls in.
 */
window.BRRIMap = (function () {
  "use strict";
  var STATIC = "/static/accidents/geo/";
  var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
  var TOMTOM_KEY = window.BRRI_TOMTOM_KEY || "";
  var BASEMAPS = {};
  // TomTom Orbis map (built on OpenStreetMap data): only offered when a key is
  // set (settings.TOMTOM_API_KEY). Shown first; falls back to "Street map".
  if (TOMTOM_KEY) {
    BASEMAPS["TomTom map"] = {
      url: "https://api.tomtom.com/maps/orbis/map-display/tile/{z}/{x}/{y}.png?apiVersion=1" +
           "&style=street-light&tileSize=256&view=Unified&key=" + encodeURIComponent(TOMTOM_KEY),
      maxNativeZoom: 19, fallback: "Street map",
      attribution: '&copy; <a href="https://www.tomtom.com" target="_blank">TomTom</a>, ' +
                   "&copy; OpenStreetMap contributors" };
  }
  var MORE_BASEMAPS = {
    // OpenFreeMap vector map (OpenStreetMap data drawn in the browser by
    // MapLibre): street names, shops, banks, schools, churches, bus stops...
    // Free, no key, no usage limits, served from a CDN. Needs maplibre-gl and
    // maplibre-gl-leaflet loaded on the page; otherwise this choice is skipped.
    // If it does not load within 10 s, the map switches itself to "Street map".
    // NOT used: raster OSM servers - OSM France "hot" timed out completely and
    // tile.openstreetmap.de answers street-level tiles with non-images
    // (Chrome blocks them: ERR_BLOCKED_BY_ORB) (both Nov 2026).
    "Detailed map": { vector: "https://tiles.openfreemap.org/styles/liberty", fallback: "Street map",
                      attribution: '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> ' +
                                   "&copy; OpenMapTiles, data &copy; OpenStreetMap contributors" },
    "Street map": { url: ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                    attribution: "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, OpenStreetMap contributors" },
    "Satellite": { url: ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}",
                   attribution: "Tiles &copy; Esri &mdash; Esri, Maxar, Earthstar Geographics" },
  };

  Object.keys(MORE_BASEMAPS).forEach(function (n) { BASEMAPS[n] = MORE_BASEMAPS[n]; });

  var geoCache = {};
  function loadGeo(name) {
    if (!geoCache[name]) {
      geoCache[name] = fetch(STATIC + name + ".geojson").then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      });
    }
    return geoCache[name];
  }

  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

  function note(el, text) {
    var n = el.querySelector(".map-note");
    if (!n) {
      n = document.createElement("div");
      n.className = "map-note";
      el.appendChild(n);
    }
    n.textContent = text;
    n.hidden = !text;
  }

  /** MapLibre vector background; falls back to cfg.fallback if it never finishes loading. */
  function vectorLayer(map, el, name, cfg, layers) {
    var layer = L.maplibreGL({ style: cfg.vector, attribution: cfg.attribution });
    var watchdog = null, loadedOnce = false, tileErrors = 0;
    function giveUp() {
      clearTimeout(watchdog);
      if (!map.hasLayer(layer)) return;
      var fb = layers[cfg.fallback];
      if (!fb) { note(el, "Background map could not load. Check the internet connection. Boundaries are still shown."); return; }
      map.removeLayer(layer);
      fb.addTo(map);
      note(el, name + " is not responding - showing " + cfg.fallback + " instead.");
      setTimeout(function () {
        var n = el.querySelector(".map-note");
        if (n && /not responding/.test(n.textContent)) note(el, "");
      }, 5000);
    }
    layer.on("add", function () {
      var gl = layer.getMaplibreMap();
      if (!gl || gl._brriHooked) return;
      gl._brriHooked = true;
      var slow = setTimeout(function () { if (!loadedOnce) note(el, "Loading map details…"); }, 1500);
      watchdog = setTimeout(function () { if (!loadedOnce) giveUp(); }, 10000);
      gl.on("load", function () {
        loadedOnce = true;
        clearTimeout(slow); clearTimeout(watchdog);
        note(el, "");
      });
      gl.on("error", function (e) {
        console.warn("Detailed map error", e && e.error);
        if (!loadedOnce && ++tileErrors >= 4) giveUp();
      });
    });
    return layer;
  }

  /** Returns {name: layer} of background maps; `first` (default "Street map") is shown. */
  function addTiles(map, el, first) {
    var layers = {};
    var canVector = !!(window.maplibregl && L.maplibreGL);
    var names = Object.keys(BASEMAPS).filter(function (n) { return !BASEMAPS[n].vector || canVector; });
    if (TOMTOM_KEY) first = "TomTom map";
    if (names.indexOf(first) < 0) first = "Street map";
    names.forEach(function (name) {
      var cfg = BASEMAPS[name], errors = 0, loaded = 0;
      if (cfg.vector) {
        layers[name] = vectorLayer(map, el, name, cfg, layers);
        if (name === first) layers[name].addTo(map);
        return;
      }
      var layer = L.tileLayer(cfg.url, { maxZoom: 19, maxNativeZoom: cfg.maxNativeZoom || 18,
                                         subdomains: cfg.subdomains || "abc",
                                         attribution: cfg.attribution });
      // Slow connections: say the map is still coming instead of showing a blank box.
      // If this map's server gives nothing at all, switch to its fallback map.
      var slowTimer = null, deadTimer = null, loadedThisRound = 0, gaveUp = false;
      function giveUp() {
        clearTimeout(slowTimer); clearTimeout(deadTimer);
        if (gaveUp || !map.hasLayer(layer)) return;
        gaveUp = true;
        var fb = cfg.fallback && layers[cfg.fallback];
        if (fb) {
          map.removeLayer(layer);
          fb.addTo(map);                       // the layer menu follows automatically
          note(el, name + " is not responding - showing " + cfg.fallback + " instead.");
          setTimeout(function () { var n = el.querySelector(".map-note"); if (n && /not responding/.test(n.textContent)) note(el, ""); }, 5000);
        } else {
          note(el, "Background map could not load. Check the internet connection. Boundaries are still shown.");
        }
      }
      layer.on("loading", function () {
        loadedThisRound = 0;
        clearTimeout(slowTimer); clearTimeout(deadTimer);
        slowTimer = setTimeout(function () { note(el, "Loading map details…"); }, 1500);
        deadTimer = setTimeout(function () { if (!loadedThisRound) giveUp(); }, 8000);
      });
      layer.on("load", function () { clearTimeout(slowTimer); clearTimeout(deadTimer); note(el, ""); });
      layer.on("tileload", function () { loaded += 1; loadedThisRound += 1; });
      layer.on("tileerror", function () {
        errors += 1;
        if (errors >= 4 && loaded === 0) giveUp();
      });
      layers[name] = layer;
      if (name === first) layer.addTo(map);
    });
    return layers;
  }

  // Ghana's extent (from the national outline), with a little margin.
  var GHANA = [[4.6, -3.35], [11.25, 1.3]];

  /** "Ghana" button: zoom back out to the whole country. */
  function addHomeButton(map, onClick) {
    var Home = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function () {
        var bar = L.DomUtil.create("div", "leaflet-bar");
        var a = L.DomUtil.create("a", "map-home", bar);
        a.href = "#";
        a.title = "Show all of Ghana";
        a.setAttribute("role", "button");
        a.textContent = "Ghana";
        L.DomEvent.on(a, "click", function (e) { L.DomEvent.preventDefault(e); onClick(); });
        L.DomEvent.disableClickPropagation(bar);
        return bar;
      },
    });
    new Home().addTo(map);
  }

  /**
   * Scrolling the page over the map must not zoom it by accident: the mouse
   * wheel zooms only with Ctrl (or Cmd) held; otherwise the page scrolls and a
   * short tip is shown. Touch pinch-zoom is unaffected.
   */
  function guardWheel(el) {
    var tip = L.DomUtil.create("div", "map-wheel-tip", el);
    tip.textContent = "Hold Ctrl and scroll to zoom the map";
    var timer = null;
    el.addEventListener("wheel", function (e) {
      if (e.ctrlKey || e.metaKey) return;          // let Leaflet zoom
      e.stopPropagation();                         // Leaflet never sees it; page scrolls
      tip.classList.add("show");
      clearTimeout(timer);
      timer = setTimeout(function () { tip.classList.remove("show"); }, 1200);
    }, true);
  }

  /**
   * create(elementId, {districts: true}) -> {map, ready, addOverlay, showGhana,
   *                                          fitRegion, fitDistrict}
   */
  function create(id, opts) {
    opts = opts || {};
    var el = document.getElementById(id);
    var none = function () {};
    if (!window.L) {
      el.innerHTML = '<p class="muted" style="padding:12px">The map library could not load. ' +
        "Check the internet connection and reload. GPS capture still works.</p>";
      return { map: null, ready: Promise.resolve(), addOverlay: none, showGhana: none,
               fitRegion: none, fitDistrict: none };
    }
    var ghana = L.latLngBounds(GHANA);
    var map = L.map(el, {
      preferCanvas: true,
      zoomSnap: 0.1, zoomDelta: 0.5, wheelPxPerZoomLevel: 90,    // fine steps: Ghana fills the box
      maxZoom: 19,
      maxBounds: ghana.pad(0.08), maxBoundsViscosity: 1.0,       // can't pan away from Ghana
    });
    function showGhana() { map.fitBounds(ghana, { padding: [4, 4] }); }
    function lockMinZoom() {
      // Never zoom out further than "all of Ghana fills the map".
      map.setMinZoom(map.getBoundsZoom(ghana, false, L.point(8, 8)));
    }
    showGhana();
    lockMinZoom();
    // When the box changes size (window resize, layout change), keep Ghana
    // filling it if the user is still looking at the whole country.
    function onResize() {
      var wasWhole = map.getZoom() <= map.getMinZoom() + 0.05;
      map.invalidateSize();
      lockMinZoom();
      if (wasWhole) showGhana();
    }
    if (window.ResizeObserver) new ResizeObserver(onResize).observe(el);
    else map.on("resize", lockMinZoom);
    addHomeButton(map, showGhana);
    guardWheel(el);
    var basemaps = addTiles(map, el, opts.basemap);

    // Grey out everything outside Ghana and draw the national border.
    map.createPane("mask").style.zIndex = 350;                  // above tiles, below data
    loadGeo("ghana").then(function (gj) {
      var geom = gj.features[0].geometry;
      var outer = geom.type === "Polygon" ? [geom.coordinates[0]]
        : geom.coordinates.map(function (p) { return p[0]; });
      var holes = outer.map(function (ring) {
        return ring.map(function (c) { return [c[1], c[0]]; });
      });
      var world = [[-89, -179], [-89, 179], [89, 179], [89, -179]];
      L.polygon([world].concat(holes), {
        pane: "mask", interactive: false, stroke: false,
        fillColor: cssVar("--page") || "#f9f9f7", fillOpacity: 0.82,
      }).addTo(map);
      L.polygon(holes, {
        pane: "mask", interactive: false, fill: false,
        color: cssVar("--brand") || "#10283a", weight: 2.5, opacity: 0.9,
      }).addTo(map);
    }).catch(function (e) { console.warn("Ghana outline not loaded", e); });

    function fitFeature(name, fid) {
      if (!fid) { showGhana(); return; }
      loadGeo(name).then(function (gj) {
        var f = gj.features.filter(function (x) { return String(x.properties.id) === String(fid); })[0];
        if (f) map.fitBounds(L.geoJSON(f).getBounds(), { padding: [16, 16], maxZoom: 13 });
      });
    }

    var overlays = {};
    var line = cssVar("--ink-2") || "#52514e";
    var ready = Promise.all([
      loadGeo("regions").then(function (gj) {
        overlays["Region boundaries"] = L.geoJSON(gj, {
          interactive: false,
          style: { color: line, weight: 2, fill: false, opacity: 0.9 },
        }).addTo(map);
      }),
      opts.districts === false ? null : loadGeo("districts").then(function (gj) {
        overlays["District boundaries"] = L.geoJSON(gj, {
          style: { color: line, weight: 0.6, opacity: 0.6, fillOpacity: 0, dashArray: "3 3" },
          onEachFeature: function (f, lyr) { lyr.bindTooltip(f.properties.name, { sticky: true }); },
        }).addTo(map);
      }),
    ]).catch(function (e) {
      console.warn("Boundaries not loaded", e);
    }).then(function () {
      return L.control.layers(basemaps, overlays, { collapsed: true }).addTo(map);
    });

    // Leaflet needs a size recalculation if the container was hidden/resized.
    setTimeout(function () { map.invalidateSize(); lockMinZoom(); }, 200);
    return {
      map: map,
      ready: ready,
      showGhana: showGhana,
      /** Zoom to a region / district by its database id (empty id = all of Ghana). */
      fitRegion: function (rid) { fitFeature("regions", rid); },
      fitDistrict: function (did) { fitFeature("districts", did); },
      /** Add an extra on/off layer to the layer menu (shown if visible=true). */
      addOverlay: function (name, layer, visible) {
        if (visible) layer.addTo(map);
        ready.then(function (control) { control.addOverlay(layer, name); });
      },
    };
  }

  // ---- Point in polygon --------------------------------------------------------
  function inRing(x, y, ring) {
    var inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function inPolygon(x, y, rings) {
    if (!inRing(x, y, rings[0])) return false;
    for (var k = 1; k < rings.length; k++) if (inRing(x, y, rings[k])) return false;
    return true;
  }
  function contains(geom, lng, lat) {
    if (geom.type === "Polygon") return inPolygon(lng, lat, geom.coordinates);
    if (geom.type === "MultiPolygon") {
      return geom.coordinates.some(function (p) { return inPolygon(lng, lat, p); });
    }
    return false;
  }

  /** Resolves to {id, name, region_id} or null. */
  function districtAt(lat, lng) {
    return loadGeo("districts").then(function (gj) {
      for (var i = 0; i < gj.features.length; i++) {
        if (contains(gj.features[i].geometry, lng, lat)) return gj.features[i].properties;
      }
      return null;
    }).catch(function () { return null; });
  }

  function distanceKm(a, b, c, d) {
    var R = 6371, toR = Math.PI / 180;
    var dLat = (c - a) * toR, dLng = (d - b) * toR;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(a * toR) * Math.cos(c * toR) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  return { create: create, districtAt: districtAt, distanceKm: distanceKm };
})();
