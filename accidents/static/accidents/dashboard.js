/* Dashboard: crash map + single-series bar/line charts (one colour, hover tooltips). */
(function () {
  "use strict";
  var css = getComputedStyle(document.documentElement);
  var v = function (n) { return css.getPropertyValue(n).trim(); };
  var charts = JSON.parse(document.getElementById("chart-data").textContent);
  var points = JSON.parse(document.getElementById("map-data").textContent);
  var spots = JSON.parse(document.getElementById("blackspot-data").textContent);

  var SEV = { 1: v("--sev-fatal"), 2: v("--sev-hosp"), 3: v("--sev-injured"), 4: v("--sev-damage") };
  var SEV_NAMES = { 1: "Fatal", 2: "Hospitalised", 3: "Injured not hospitalised", 4: "Damage only" };

  // ---- Map ---------------------------------------------------------------------
  var created = window.BRRIMap ? BRRIMap.create("crash-map") : null;
  var map = created ? created.map : null;
  if (map) {
    // Police stations (off by default; switch on in the layer menu).
    var stations = JSON.parse(document.getElementById("station-data").textContent);
    var stationLayer = L.layerGroup(stations.map(function (s) {
      return L.marker([s.lat, s.lng], {
        icon: L.divIcon({ className: "station-pin", html: "P", iconSize: [18, 18] }),
        title: s.name,
      }).bindTooltip(s.name + (s.district ? " · " + s.district : ""));
    }));
    created.addOverlay("Police stations (" + stations.length + ")", stationLayer, false);

    spots.forEach(function (s) {
      L.circle([s.lat, s.lng], {
        radius: 400, color: v("--sev-fatal"), weight: 2, fillOpacity: 0.08,
      }).addTo(map).bindTooltip("Blackspot: " + s.n + " accidents, " + s.killed + " killed");
    });
    // Bigger dots for more serious accidents, drawn last so they sit on top.
    var SIZE = { 1: 8, 2: 7, 3: 6, 4: 5 };
    points.slice().sort(function (a, b) { return (b.sev || 4) - (a.sev || 4); }).forEach(function (p) {
      L.circleMarker([p.lat, p.lng], {
        radius: SIZE[p.sev] || 5, weight: 1.5, color: "#ffffff", fillColor: SEV[p.sev] || SEV[4], fillOpacity: 0.95,
      }).addTo(map).bindPopup(
        '<a href="/accidents/' + p.id + '/">Report ' + p.ref + "</a><br>" + p.date + "<br>" +
        (SEV_NAMES[p.sev] || "Severity not recorded") + (p.killed ? " · " + p.killed + " killed" : ""));
    });
    // Zoom to the filtered district / region; otherwise the map shows all of Ghana.
    var params = new URLSearchParams(location.search);
    if (params.get("district")) created.fitDistrict(params.get("district"));
    else if (params.get("region")) created.fitRegion(params.get("region"));
    document.addEventListener("click", function (e) {
      var z = e.target.dataset && e.target.dataset.zoom;
      if (!z) return;
      e.preventDefault();
      var ll = z.split(",").map(Number);
      map.setView(ll, 16);
      document.getElementById("crash-map").scrollIntoView({ behavior: "smooth" });
    });
  }

  // ---- Charts ---------------------------------------------------------------------
  if (!window.Chart) return;
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.color = v("--ink-2");
  Chart.defaults.borderColor = v("--grid");

  function axes(horizontal) {
    var valueAxis = { beginAtZero: true, ticks: { precision: 0 }, grid: { color: v("--grid") },
                      border: { display: false } };
    var catAxis = { grid: { display: false }, border: { color: v("--axis") } };
    return horizontal ? { x: valueAxis, y: catAxis } : { x: catAxis, y: valueAxis };
  }

  function empty(id, rows) {
    if (rows.some(function (r) { return r.n > 0; })) return false;
    var box = document.getElementById(id).parentElement;
    box.style.height = "auto";
    box.innerHTML = '<p class="muted">No data for these filters.</p>';
    return true;
  }

  function bar(key, opts) {
    opts = opts || {};
    var rows = charts[key], id = "c-" + key;
    if (empty(id, rows)) return;
    new Chart(document.getElementById(id), {
      type: "bar",
      data: {
        labels: rows.map(function (r) { return r.label; }),
        datasets: [{
          label: opts.label || "Accidents",
          data: rows.map(function (r) { return r.n; }),
          backgroundColor: opts.colors || v("--series-1"),
          borderRadius: 4, borderSkipped: "start", maxBarThickness: 28, categoryPercentage: 0.8,
        }],
      },
      options: {
        indexAxis: opts.horizontal ? "y" : "x",
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: axes(opts.horizontal),
      },
    });
  }

  var month = charts.month;
  if (!empty("c-month", month)) {
    new Chart(document.getElementById("c-month"), {
      type: "line",
      data: {
        labels: month.map(function (r) { return r.label; }),
        datasets: [{
          label: "Accidents", data: month.map(function (r) { return r.n; }),
          borderColor: v("--series-1"), backgroundColor: v("--series-1"),
          borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, tension: 0,
        }],
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false } },
        scales: axes(false),
      },
    });
  }

  // Labels come from codebook.ACCIDENT_SEVERITY; the category name sits on the axis,
  // so colour is never the only cue.
  var BY_LABEL = { "Fatal": SEV[1], "Hospitalised": SEV[2], "Injured Not-Hospitalised": SEV[3] };
  var sevColors = charts.severity.map(function (r) { return BY_LABEL[r.label] || SEV[4]; });

  bar("region", { horizontal: true });
  bar("severity", { horizontal: true, colors: sevColors });
  bar("road_users", { label: "Casualties" });
})();
