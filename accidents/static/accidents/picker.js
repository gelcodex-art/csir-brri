/*
 * Site location on the report form: put a pin on the exact spot.
 *
 * Search is only a helper to get the map near the place - police landmarks
 * ("Tech Roundabout", "Bomso Traffic Light") are often not in any map index.
 * So the map opens at the chosen police station, and the person clicks the
 * spot. Places pinned on earlier reports are offered first in the search, so
 * a landmark only has to be found by hand once.
 */
(function () {
  "use strict";
  var form = document.getElementById("accident-form");
  var el = document.getElementById("pick-map");
  if (!form || !el || !window.BRRIMap) return;

  var $ = function (name) { return form.querySelector('[name="' + name + '"]'); };
  var latIn = $("latitude"), lngIn = $("longitude"), typed = $("site_location_text");
  var region = $("region"), station = $("police_station");
  var status = document.getElementById("loc-status");
  var clearBtn = document.getElementById("loc-clear");
  var search = document.getElementById("loc-search");
  var results = document.getElementById("loc-results");
  var PIN_ZOOM = 14;            // a click places the pin only when zoomed in at least this far

  var created = BRRIMap.create("pick-map", { basemap: "Detailed map" });
  var map = created.map;
  if (!map) return;

  var pinIcon = L.divIcon({
    className: "loc-pin", iconSize: [30, 42], iconAnchor: [15, 41],
    html: '<svg viewBox="0 0 32 44"><path d="M16 1C7.700 1 1 7.700 1 16c0 11 15 27 15 27s15-16 15-27C31 7.700 24.300 1 16 1z"/><circle cx="16" cy="16" r="6"/></svg>',
  });
  var marker = null;

  function say(title, text, kind) {
    status.className = "loc-status" + (kind ? " " + kind : "");
    status.innerHTML = "";
    var b = document.createElement("strong"); b.textContent = title;
    var s = document.createElement("span"); s.textContent = text;
    status.appendChild(b); status.appendChild(s);
  }

  function current() {
    var lat = parseFloat(latIn.value), lng = parseFloat(lngIn.value);
    return isFinite(lat) && isFinite(lng) ? [lat, lng] : null;
  }

  /** Put the pin at lat/lng. `write` = also fill the latitude/longitude boxes. */
  function setPin(lat, lng, write) {
    if (write) {
      latIn.value = lat.toFixed(6);
      lngIn.value = lng.toFixed(6);
    }
    if (!marker) {
      marker = L.marker([lat, lng], { icon: pinIcon, draggable: true, autoPan: true }).addTo(map);
      marker.on("dragend", function () {
        var p = marker.getLatLng();
        setPin(p.lat, p.lng, true);
      });
    } else {
      marker.setLatLng([lat, lng]);
    }
    clearBtn.hidden = false;
    say("Pin placed", lat.toFixed(5) + ", " + lng.toFixed(5) + " - drag the pin to adjust.", "ok");
    BRRIMap.districtAt(lat, lng).then(function (d) {
      var now = current();
      if (!now || Math.abs(now[0] - lat) > 1e-6 || Math.abs(now[1] - lng) > 1e-6) return;
      if (d) say("Pin placed in " + d.name, lat.toFixed(5) + ", " + lng.toFixed(5) + " - drag the pin to adjust.", "ok");
      else say("The pin is outside Ghana", "Click the right spot on the map again.", "bad");
    });
  }

  function clearPin() {
    latIn.value = ""; lngIn.value = "";
    if (marker) { map.removeLayer(marker); marker = null; }
    clearBtn.hidden = true;
    say("No pin on the map yet", "Zoom in to the place and click the exact spot.");
  }

  map.on("click", function (e) {
    if (map.getZoom() < PIN_ZOOM) {
      // Too far out to be exact: come closer to where they clicked instead.
      map.setView(e.latlng, Math.min(PIN_ZOOM + 1, map.getZoom() + 4));
      if (!current()) say("Zoomed in - now click the exact spot", "The pin is placed once roads and junctions are visible.");
      return;
    }
    setPin(e.latlng.lat, e.latlng.lng, true);
  });
  clearBtn.addEventListener("click", clearPin);

  // Coordinates typed by hand move the pin.
  function fromBoxes() {
    var p = current();
    if (p) { setPin(p[0], p[1], false); map.setView(p, Math.max(map.getZoom(), 16)); }
    else if (!latIn.value && !lngIn.value) clearPin();
  }
  latIn.addEventListener("change", fromBoxes);
  lngIn.addEventListener("change", fromBoxes);

  // ---- Where the map opens: saved pin > police station > region > Ghana -------------
  var stations = [], towns = [], districtRegion = {}, regionNames = {}, districtNames = {};
  function stationPoint() {
    var s = stations.filter(function (x) { return String(x[0]) === station.value; })[0];
    return s && s[5] != null ? [s[5], s[6]] : null;
  }
  function goToArea() {
    if (current()) return;                       // never move away from a placed pin
    var p = stationPoint();
    if (p) map.setView(p, 14);
    else if (region.value) created.fitRegion(region.value);
    else created.showGhana();
  }
  region.addEventListener("change", function () { setTimeout(goToArea, 0); });
  station.addEventListener("change", goToArea);

  var start = current();
  if (start) { setPin(start[0], start[1], false); map.setView(start, 16); }

  fetch("/api/locations.json", { credentials: "same-origin" }).then(function (r) { return r.json(); })
    .then(function (data) {
      stations = data.stations; towns = data.towns;
      data.regions.forEach(function (r) { regionNames[r[0]] = r[1]; });
      data.districts.forEach(function (d) { districtRegion[d[0]] = d[1]; districtNames[d[0]] = d[2]; });
      setTimeout(goToArea, 50);                  // after app.js has rebuilt the station list
    }).catch(function (e) { console.warn("Locations not loaded", e); });

  // ---- Search: earlier pins, then towns/suburbs, then an online place search ---------
  var seq = 0, timer = null;
  function near() {                              // where to look first
    return current() || stationPoint() || [map.getCenter().lat, map.getCenter().lng];
  }

  function show(items, note) {
    results.innerHTML = "";
    items.forEach(function (it) {
      var li = document.createElement("li");
      li.tabIndex = 0;
      var tag = document.createElement("span"); tag.className = "tag " + it.kind; tag.textContent = it.tag;
      var body = document.createElement("div");
      var name = document.createElement("strong"); name.textContent = it.name;
      var sub = document.createElement("small"); sub.textContent = it.sub;
      body.appendChild(name); body.appendChild(sub);
      li.appendChild(tag); li.appendChild(body);
      function pick() {
        results.hidden = true;
        if (it.kind === "pinned") {
          setPin(it.lat, it.lng, true);
          map.setView([it.lat, it.lng], 17);
          say("Pin placed where \"" + it.name + "\" was pinned before", "Check it is the same spot; drag the pin to adjust.", "ok");
        } else {
          map.setView([it.lat, it.lng], it.kind === "place" ? 17 : 15);
          if (!current()) say("Now click the exact spot", "The map is at " + it.name + ". Move it if needed, then click where the accident happened.");
        }
      }
      li.addEventListener("click", pick);
      li.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); pick(); } });
      results.appendChild(li);
    });
    if (note) {
      var li = document.createElement("li");
      li.className = "note"; li.textContent = note;
      results.appendChild(li);
    }
    results.hidden = !results.children.length;
  }

  function localTowns(q) {
    var words = q.toLowerCase().split(/[\s,]+/).filter(function (w) { return w.length > 2; });
    if (!words.length) return [];
    var here = near(), rid = Number(region.value);
    var hits = [];
    for (var i = 0; i < towns.length; i++) {
      var t = towns[i];
      if (t[5] == null) continue;
      var name = t[2].toLowerCase();
      var whole = name.indexOf(q.toLowerCase()) === 0;
      var word = words.some(function (w) { return name === w || name.indexOf(w) === 0; });
      if (!whole && !word) continue;
      var d = BRRIMap.distanceKm(here[0], here[1], t[5], t[6]);
      if (rid && districtRegion[t[1]] !== rid) d += 1000;     // other regions last
      hits.push({ kind: "town", tag: "Town", name: t[2], lat: t[5], lng: t[6], d: d,
                  sub: (districtNames[t[1]] || "") + ", " + (regionNames[districtRegion[t[1]]] || "") });
    }
    hits.sort(function (a, b) { return a.d - b.d; });
    return hits.slice(0, 5);
  }

  function run(q) {
    var mine = ++seq;
    q = q.trim();
    if (q.length < 3) { results.hidden = true; return; }
    var items = localTowns(q);
    show(items, "Searching...");
    var here = near();
    var pinned = fetch("/api/pins.json?q=" + encodeURIComponent(q), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { pins: [] }; })
      .then(function (d) {
        return d.pins.map(function (p) {
          return { kind: "pinned", tag: "Pinned before", name: p.name, lat: p.lat, lng: p.lng,
                   sub: "Report " + p.report + " - click to use the same spot" };
        });
      }).catch(function () { return []; });
    // Photon: free OpenStreetMap place search, limited to Ghana, nearest results first.
    var online = fetch("https://photon.komoot.io/api/?limit=6&bbox=-3.35,4.6,1.3,11.25&lat=" + here[0] +
                       "&lon=" + here[1] + "&q=" + encodeURIComponent(q))
      .then(function (r) { return r.ok ? r.json() : { features: [] }; })
      .then(function (d) {
        return d.features.filter(function (f) { return f.properties.name; }).map(function (f) {
          var p = f.properties, c = f.geometry.coordinates;
          var km = BRRIMap.distanceKm(here[0], here[1], c[1], c[0]);
          return { kind: "place", tag: "Map", name: p.name, lat: c[1], lng: c[0], d: km,
                   sub: [p.city || p.county || p.district || "", p.state || ""].filter(Boolean).join(", ") +
                        " - " + (km < 10 ? km.toFixed(1) : Math.round(km)) + " km away" };
        }).sort(function (a, b) { return a.d - b.d; }).slice(0, 4);
      }).catch(function () { return []; });
    Promise.all([pinned, online]).then(function (r) {
      if (mine !== seq) return;
      var all = r[0].concat(items, r[1]);
      show(all, all.length
        ? "Not the right place? Move the map yourself and click the spot."
        : "Nothing found for \"" + q + "\". Move the map yourself and click the spot - it will be offered here next time.");
    });
  }

  search.addEventListener("input", function () {
    clearTimeout(timer);
    var q = search.value;
    timer = setTimeout(function () { run(q); }, 350);
  });
  search.addEventListener("focus", function () { if (results.children.length && search.value.trim().length >= 3) results.hidden = false; });
  search.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); clearTimeout(timer); run(search.value); }   // never submits the report
    if (e.key === "Escape") results.hidden = true;
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".loc-search")) results.hidden = true;
  });

  // The place typed in words is looked up straight away, if there is no pin yet.
  typed.addEventListener("change", function () {
    var text = typed.value.trim();
    if (!text || current() || search.value.trim()) return;
    search.value = text.split("\n")[0].slice(0, 80);
    run(search.value);
  });
})();
