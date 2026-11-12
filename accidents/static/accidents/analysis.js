/* Analysis page: changing a choice reloads the table; one bar chart of the same numbers. */
(function () {
  "use strict";
  var form = document.getElementById("filters");
  document.querySelectorAll("#analysis-pick [data-auto]").forEach(function (el) {
    el.addEventListener("change", function () { form.submit(); });
  });

  var holder = document.getElementById("analysis-data");
  var canvas = document.getElementById("analysis-chart");
  if (!holder || !canvas || !window.Chart) return;
  var chart = JSON.parse(holder.textContent);

  var css = getComputedStyle(document.documentElement);
  var v = function (n) { return css.getPropertyValue(n).trim(); };
  // Colours are given to the columns in a fixed order (see --cat-1..8 in app.css).
  var COLORS = [1, 2, 3, 4, 5, 6, 7, 8].map(function (i) { return v("--cat-" + i); });
  var many = chart.series.length > 1;
  var unit = chart.percent ? "%" : "";

  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.color = v("--ink-2");
  Chart.defaults.borderColor = v("--grid");

  // Room for every bar: horizontal charts grow with the number of groups.
  var box = document.getElementById("analysis-box");
  if (chart.horizontal) {
    var perGroup = many && !chart.stacked ? Math.max(30, chart.series.length * 13 + 10) : 30;
    box.style.height = Math.max(260, chart.labels.length * perGroup + 60) + "px";
  } else {
    box.style.height = "380px";
  }

  if (many) {
    var legend = document.getElementById("analysis-legend");
    chart.series.forEach(function (s, i) {
      var item = document.createElement("span");
      var swatch = document.createElement("i");
      swatch.style.background = COLORS[i % COLORS.length];
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(s.name));
      legend.appendChild(item);
    });
  }

  var valueAxis = {
    beginAtZero: true, stacked: chart.stacked, grid: { color: v("--grid") }, border: { display: false },
    ticks: { precision: 0, callback: function (val) { return val.toLocaleString() + unit; } },
  };
  if (chart.percent && chart.stacked) valueAxis.max = 100;
  var groupAxis = { stacked: chart.stacked, grid: { display: false }, border: { color: v("--axis") } };

  new Chart(canvas, {
    type: "bar",
    data: {
      labels: chart.labels,
      datasets: chart.series.map(function (s, i) {
        return {
          label: s.name, data: s.data, backgroundColor: COLORS[i % COLORS.length],
          // Stacked segments are separated by a thin line of the card colour.
          borderColor: v("--surface"), borderWidth: chart.stacked ? 1 : 0,
          borderRadius: chart.stacked ? 0 : 4, borderSkipped: "start",
          maxBarThickness: 26, categoryPercentage: 0.82, barPercentage: many && !chart.stacked ? 0.92 : 0.8,
        };
      }),
    },
    options: {
      indexAxis: chart.horizontal ? "y" : "x",
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false, axis: chart.horizontal ? "y" : "x" },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              var n = chart.horizontal ? ctx.parsed.x : ctx.parsed.y;
              return " " + ctx.dataset.label + ": " + n.toLocaleString() + unit;
            },
          },
        },
      },
      scales: chart.horizontal ? { x: valueAxis, y: groupAxis } : { x: groupAxis, y: valueAxis },
    },
  });
})();
