/*
 * Data-entry form behaviour:
 *  - Region -> police station dropdown (stations of the chosen region), using
 *    /api/locations.json.
 *  - Repeating rows for vehicles, passengers and pedestrians.
 */
(function () {
  "use strict";
  var form = document.getElementById("accident-form");
  if (!form) return;

  var $ = function (name) { return form.querySelector('[name="' + name + '"]'); };

  // ---- 2-3 Region -> police station dropdown, from /api/locations.json ------------
  // Stations: [id, region_id, district_id, name, kind, lat, lng, codes ("02041 12001")]
  var region = $("region"), station = $("police_station"), newStation = $("new_police_station");
  var stations = [];

  function refreshStations(keep) {
    var current = keep != null ? String(keep) : station.value;
    var rid = Number(region.value);
    var inRegion = stations.filter(function (s) { return s[1] === rid; });
    station.innerHTML = "";
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = !rid ? "Choose a region first" : "Select...";
    station.appendChild(blank);
    inRegion.forEach(function (s) {
      var o = document.createElement("option");
      o.value = s[0];
      o.textContent = s[3] + (s[7] ? "  (" + s[7].split(" ").join(", ") + ")" : "");
      station.appendChild(o);
    });
    // Last choice: opens the box for typing a station that is not listed.
    if (rid) {
      var other = document.createElement("option");
      other.value = "";
      other.dataset.other = "1";
      other.textContent = "My station is not in the list...";
      station.appendChild(other);
    }
    station.value = inRegion.some(function (s) { return String(s[0]) === current; }) ? current : "";
    if (!station.value && rid && (typingStation || newStation.value.trim())) {
      station.selectedIndex = station.options.length - 1;
    }
    showNewStation(false);
  }

  // "Station not in the list? Type its name" appears only when that choice is made.
  var typingStation = !!newStation.value.trim();
  function showNewStation(focus) {
    var opt = station.options[station.selectedIndex];
    typingStation = !!(opt && opt.dataset.other);
    var box = newStation.closest(".field");
    var wasHidden = box.hidden;
    box.hidden = !typingStation && !newStation.value.trim();
    if (wasHidden && !box.hidden && focus) { box.classList.add("follow-up"); newStation.focus(); }
  }

  region.addEventListener("change", function () { refreshStations(); });
  station.addEventListener("change", function () {
    var opt = station.options[station.selectedIndex];
    if (!(opt && opt.dataset.other)) newStation.value = "";
    showNewStation(true);
    showStationCode();
  });

  // ---- 3 Police station code (04086): chooses the region and the station ------------
  var stationCode = $("station_code");
  var codeNote = null;
  function sayCode(text, bad) {
    if (!stationCode) return;
    if (!codeNote) {
      codeNote = document.createElement("p");
      stationCode.closest(".field").appendChild(codeNote);
    }
    codeNote.className = bad ? "err" : "muted";
    codeNote.textContent = text;
    codeNote.hidden = !text;
  }
  function stationByCode(code) {
    return stations.filter(function (s) { return s[7] && s[7].split(" ").indexOf(code) >= 0; })[0];
  }
  /** The code box follows the station chosen from the list. */
  function showStationCode() {
    if (!stationCode) return;
    var s = stations.filter(function (x) { return String(x[0]) === station.value; })[0];
    var codes = s && s[7] ? s[7].split(" ") : [];
    if (codes.indexOf(stationCode.value) < 0) stationCode.value = codes[0] || "";
    sayCode("");
  }
  function useStationCode() {
    var typed = stationCode.value.trim();
    if (!typed) { sayCode(""); return; }
    if (!/^\d{3,5}$/.test(typed)) { sayCode("A station code is five digits, for example 04086.", true); return; }
    var code = ("00000" + typed).slice(-5);
    var s = stationByCode(code);
    stationCode.value = code;
    if (!s) { sayCode("Code " + code + " is not in the code list. Choose the station from the list below.", true); return; }
    if (region.value !== String(s[1])) {
      region.value = String(s[1]);
      region.dispatchEvent(new Event("change", { bubbles: true }));
    }
    station.value = String(s[0]);
    newStation.value = "";
    station.dispatchEvent(new Event("change", { bubbles: true }));
    stationCode.value = code;
    sayCode(s[3]);
  }
  if (stationCode) stationCode.addEventListener("change", useStationCode);
  showNewStation(false);

  var initialStation = station.value;
  station.disabled = true;
  fetch("/api/locations.json", { credentials: "same-origin" }).then(function (r) {
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }).then(function (payload) {
    stations = payload.stations;
    station.disabled = false;
    refreshStations(initialStation);
    if (stationCode && stationCode.value && !station.value) useStationCode();
  }).catch(function (e) {
    console.error(e);
    station.disabled = false;
  });

  // ---- Repeating rows (vehicles, passengers, pedestrians) ----------------------------
  // "4 No. of vehicles involved" and the vehicle sections are kept in step:
  // changing the number adds/removes sections; adding/removing sections updates it.
  var numVehicles = $("num_vehicles");
  var MAX_VEHICLES = 30;

  function isDeleted(card) {
    var del = card.querySelector('input[name$="-DELETE"]');
    return !!(del && del.checked);
  }
  function vehicleCards() {
    return Array.prototype.slice.call(document.querySelectorAll("#vehicles-rows .vehicle"));
  }
  function activeVehicles() {
    return vehicleCards().filter(function (c) { return !isDeleted(c); });
  }
  function hasDetails(card) {
    return Array.prototype.some.call(card.querySelectorAll("input, select, textarea"), function (el) {
      if (el.type === "hidden" || el.type === "checkbox" || /-vehicle_no$/.test(el.name)) return false;
      return el.value !== "";
    });
  }

  function renumberVehicles() {
    var n = 0;
    vehicleCards().forEach(function (card) {
      var title = card.querySelector("h3 span");
      var vno = card.querySelector('[name$="-vehicle_no"]');
      if (isDeleted(card)) {
        title.textContent = "Vehicle (will be deleted when saved)";
        card.style.opacity = 0.55;
        return;
      }
      n += 1;
      title.textContent = "Vehicle " + n;
      card.style.opacity = "";
      if (vno) vno.value = n;
    });
    if (numVehicles) numVehicles.value = n || "";
  }

  function addRow(prefix) {
    var total = form.querySelector('[name="' + prefix + '-TOTAL_FORMS"]');
    var idx = Number(total.value);
    var html = document.getElementById(prefix + "-empty").innerHTML.replace(/__prefix__/g, idx);
    var holder = document.createElement(prefix === "vehicles" ? "div" : "tbody");
    holder.innerHTML = html.trim();
    var row = holder.firstElementChild;
    document.getElementById(prefix + "-rows").appendChild(row);
    total.value = idx + 1;
    return row;
  }

  /** Make the number of vehicle sections equal to `wanted`. */
  function syncVehicles(wanted) {
    var active = activeVehicles();
    if (wanted > MAX_VEHICLES) {
      alert("A report can have at most " + MAX_VEHICLES + " vehicles.");
      wanted = MAX_VEHICLES;
    }
    // Add sections (re-using any section that was marked for deletion first).
    vehicleCards().filter(isDeleted).forEach(function (card) {
      if (activeVehicles().length < wanted) card.querySelector('input[name$="-DELETE"]').checked = false;
    });
    while (activeVehicles().length < wanted) addRow("vehicles");
    // Remove sections from the end.
    active = activeVehicles();
    var extra = active.slice(wanted);
    if (extra.length) {
      var withData = extra.filter(hasDetails);
      if (withData.length && !confirm("Remove " + extra.map(function (c) {
        return c.querySelector("h3 span").textContent; }).join(", ") +
        "? Details already entered for " + (withData.length === 1 ? "it" : "them") + " will be lost.")) {
        renumberVehicles();               // cancelled: put the number back
        return;
      }
      extra.forEach(function (card) {
        var del = card.querySelector('input[name$="-DELETE"]');
        if (del) del.checked = true;      // saved vehicle: delete on save
        else card.remove();               // new section: just drop it
      });
      reindex("vehicles");
    }
    renumberVehicles();
  }

  if (numVehicles) {
    numVehicles.min = 1;
    numVehicles.max = MAX_VEHICLES;
    numVehicles.addEventListener("change", function () {
      var n = parseInt(numVehicles.value, 10);
      if (!n || n < 1) { renumberVehicles(); return; }   // blank/0: keep sections
      syncVehicles(n);
    });
  }

  document.querySelectorAll("[data-add]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var prefix = btn.dataset.add;
      if (prefix === "vehicles") {
        syncVehicles(activeVehicles().length + 1);
      } else {
        addRow(prefix);
      }
    });
  });
  form.addEventListener("change", function (ev) {
    if (/^vehicles-\d+-DELETE$/.test(ev.target.name || "")) renumberVehicles();
  });

  // After removing an unsaved row, re-index the remaining unsaved rows so the
  // formset indices stay contiguous (saved rows keep theirs; they use Delete).
  function reindex(prefix) {
    var initial = Number(form.querySelector('[name="' + prefix + '-INITIAL_FORMS"]').value);
    var re = new RegExp("^(id_)?" + prefix + "-\\d+-");
    var rows = Array.prototype.filter.call(
      document.getElementById(prefix + "-rows").children,
      function (r) { return r.querySelector("[data-remove]"); });
    rows.forEach(function (row, i) {
      var idx = initial + i;
      row.querySelectorAll("[name], [id], label[for]").forEach(function (el) {
        ["name", "id", "for"].forEach(function (attr) {
          var v = el.getAttribute(attr);
          if (v && re.test(v)) el.setAttribute(attr, v.replace(re, "$1" + prefix + "-" + idx + "-"));
        });
      });
    });
    form.querySelector('[name="' + prefix + '-TOTAL_FORMS"]').value = initial + rows.length;
  }

  form.addEventListener("click", function (ev) {
    if (ev.target.hasAttribute("data-remove")) {
      var row = ev.target.closest(".formrow");
      var prefix = row.parentElement.id.replace(/-rows$/, "");
      row.remove();
      reindex(prefix);
      renumberVehicles();
    }
  });
  // Prevent double-clicks on "Save report" / "Save anyway" creating the report twice.
  form.addEventListener("submit", function (ev) {
    var clicked = ev.submitter;
    setTimeout(function () {       // after the browser has captured the clicked button's value
      form.querySelectorAll('button[type="submit"]').forEach(function (b) { b.disabled = true; });
      if (clicked) clicked.textContent = "Saving...";
    }, 0);
  });

  // ---- Problem list after "Save report" (see checks.py) ------------------------------
  var summary = document.getElementById("check-summary");
  if (summary) {
    summary.scrollIntoView({ block: "start" });
    summary.focus({ preventScroll: true });
  }
  document.addEventListener("click", function (ev) {
    var link = ev.target.closest && ev.target.closest("[data-goto]");
    if (!link) return;
    ev.preventDefault();
    var target = document.getElementById(link.dataset.goto);
    if (!target) return;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    var box = target.closest(".field, td, section") || target;
    box.classList.remove("flash");
    void box.offsetWidth;                       // restart the highlight animation
    box.classList.add("flash");
    if (target.focus) setTimeout(function () { target.focus({ preventScroll: true }); }, 350);
  });

  // ---- 5-7 Date -> 8 Day of week (codes as on the paper form) -----------------------
  var DOW = ["7 - Sunday", "1 - Monday", "2 - Tuesday", "3 - Wednesday", "4 - Thursday",
             "5 - Friday", "6 - Saturday"];
  var accDate = $("accident_date"), dow = $("day_of_week_display");
  function updateDayOfWeek() {
    var p = (accDate.value || "").split("-").map(Number);       // "YYYY-MM-DD"
    dow.value = p.length === 3 && p[0] ? DOW[new Date(p[0], p[1] - 1, p[2]).getDay()] : "";
  }
  if (accDate && dow) {
    accDate.addEventListener("change", updateDayOfWeek);
    accDate.addEventListener("input", updateDayOfWeek);
    updateDayOfWeek();
  }

  // On load: show at least the number of vehicles already entered (never fewer
  // sections than exist), and one section for a new report.
  var startCount = Math.max(parseInt(numVehicles && numVehicles.value, 10) || 0,
                            activeVehicles().length, 1);
  while (activeVehicles().length < Math.min(startCount, MAX_VEHICLES)) addRow("vehicles");
  renumberVehicles();

  // ---- Follow-up questions: shown only when the answer before them needs them --------
  // Each rule: the follow-up field(s), the question they depend on, and when to hide.
  // `fill` is the answer written into a hidden field (e.g. no shoulder -> 18 "No Shoulder").
  // A hidden field is emptied, so nothing is saved that the person cannot see - except
  // when the page opens with something already in it: then it stays visible.
  var REPORT_RULES = [
    { fields: ["bridge_river_name"], on: "road_description", hideUnless: ["5"] },          // 15 Bridge
    { fields: ["shoulder_condition"], on: "shoulder_type", hideIf: ["3"], fill: "4" },     // 17 No Shoulder
  ];
  var LICENCE = ["licence_no", "licence_place_of_issue", "licence_issue_date", "licence_expiry_date"];
  var DRIVER = ["registration_no", "registration_code", "driver_name", "driver_sex", "driver_age", "driver_nationality",
                "driver_injury", "driver_education", "licence_status", "drink_drugs"].concat(LICENCE);
  var VEHICLE_RULES = [
    { fields: DRIVER, on: "vehicle_type", hideIf: ["10"] },                                 // 29 Unknown
    { fields: ["registration_no", "registration_code", "licence_status"].concat(LICENCE), on: "vehicle_type", hideIf: ["8"] },  // Bicycle
    { fields: LICENCE, on: "licence_status", hideIf: ["4"] },                               // 42 Unlicensed
  ];

  function applyRules(rules, find, firstRun) {
    var hide = {}, all = {};                         // hide: field name -> value to leave in it
    rules.forEach(function (r) {
      r.fields.forEach(function (n) { all[n] = 1; });
      var q = find(r.on);
      if (!q) return;
      var off = r.hideIf ? r.hideIf.indexOf(q.value) >= 0 : r.hideUnless.indexOf(q.value) < 0;
      if (off) r.fields.forEach(function (n) { hide[n] = r.fill || ""; });
    });
    Object.keys(all).forEach(function (n) {
      var el = find(n);
      if (!el) return;
      var box = el.closest(".field");
      if (n in hide) {
        if (firstRun && el.value !== "" && el.value !== hide[n]) box.dataset.kept = "1";
        if (box.dataset.kept) return;                 // saved earlier: stays in view until the question changes
        if (box.hidden && el.value === hide[n]) return;
        el.value = hide[n];
        if (hide[n]) el.dataset.filled = "1";
        box.hidden = true;
      } else if (box.hidden) {
        if (el.dataset.filled) { el.value = ""; delete el.dataset.filled; }
        box.hidden = false;
        if (!firstRun) box.classList.add("follow-up");
      }
    });
  }

  function applyAllRules(firstRun) {
    applyRules(REPORT_RULES, $, firstRun);
    vehicleCards().forEach(function (card) {
      var first = firstRun || !card.dataset.ruled;
      card.dataset.ruled = "1";
      applyRules(VEHICLE_RULES, function (n) { return card.querySelector('[name$="-' + n + '"]'); }, first);
      var type = card.querySelector('[name$="-vehicle_type"]');
      var note = card.querySelector("[data-driver-note]");
      if (note && type) note.hidden = type.value !== "10";
    });
  }

  // ---- Passenger / pedestrian tables: a plain sentence until someone is added --------
  function showTables() {
    ["passengers", "pedestrians"].forEach(function (prefix) {
      var rows = document.getElementById(prefix + "-rows");
      var none = form.querySelector('[data-none="' + prefix + '"]');
      rows.closest(".table-wrap").hidden = !rows.children.length;
      if (none) none.hidden = !!rows.children.length;
    });
  }

  // ---- 10 Killed, 11 Injured, 12 Severity: counted from the people entered -----------
  // Same rule as checks.py: drivers (40), passengers (49) and pedestrians (55).
  var killed = $("killed"), injured = $("injured"), severity = $("severity");
  [killed, injured, severity].forEach(function (el) {
    if (!el) return;
    el.classList.add("auto");
    el.tabIndex = -1;
    if (el.tagName === "INPUT") el.readOnly = true;
  });
  function countPeople() {
    var sevs = [];
    activeVehicles().forEach(function (card) {
      var v = card.querySelector('[name$="-driver_injury"]').value;
      if (v === "1" || v === "2" || v === "3") sevs.push(Number(v));
    });
    ["passengers", "pedestrians"].forEach(function (prefix) {
      Array.prototype.forEach.call(document.getElementById(prefix + "-rows").children, function (row) {
        if (isDeleted(row)) return;
        var v = row.querySelector('[name$="-severity"]').value;
        if (v) sevs.push(Number(v));
      });
    });
    var fatal = sevs.filter(function (s) { return s === 1; }).length;
    killed.value = fatal;
    injured.value = sevs.length - fatal;
    severity.value = sevs.length ? Math.min.apply(null, sevs) : 4;
  }

  // 25 "Hit Pedestrian": open a pedestrian row straight away if there is none.
  var collision = $("collision_type");
  if (collision) {
    collision.addEventListener("change", function () {
      if (collision.value === "9" && !document.getElementById("pedestrians-rows").children.length) {
        addRow("pedestrians");
      }
    });
  }

  // ---- 1 Report number typed the old way: "237/15" -> number 237, year 2015 ----------
  var repNo = $("report_number"), repYear = $("report_year");
  function fullYear(y) {
    y = Number(y);
    if (y >= 100) return y;
    return y <= new Date().getFullYear() % 100 + 1 ? 2000 + y : 1900 + y;
  }
  if (repNo && repYear) {
    repNo.addEventListener("change", function () {
      var m = /^(.*\S)\s*\/\s*(\d{2}|\d{4})$/.exec(repNo.value.trim());
      if (!m) return;
      repNo.value = m[1].trim();
      repYear.value = fullYear(m[2]);
    });
    repYear.addEventListener("change", function () {
      if (/^\d{1,2}$/.test(repYear.value.trim())) repYear.value = fullYear(repYear.value);
    });
  }

  // ---- 60 Town/village code: the coding manual's towns for the chosen region ---------
  var townCode = $("town_code");
  var townCodes = JSON.parse((document.getElementById("town-codes") || {}).textContent || "{}");
  function refreshTownCodes() {
    if (!townCode) return;
    var keep = townCode.value;
    var extra = Array.prototype.filter.call(townCode.options, function (o) {
      return / \(not in the code list\)$/.test(o.text);           // a saved old value: keep it
    });
    var list = townCodes[region.value] || [];
    townCode.length = 1;
    townCode.options[0].text = region.value ? "Select..." : "Choose the region (2) first";
    list.forEach(function (c) { townCode.add(new Option(c[1], c[0])); });
    extra.forEach(function (o) { townCode.add(new Option(o.text, o.value)); });
    townCode.value = Array.prototype.some.call(townCode.options, function (o) { return o.value === keep; }) ? keep : "";
  }
  region.addEventListener("change", refreshTownCodes);
  refreshTownCodes();

  // ---- 30 Registration code: worked out from the number plate's region letters ------
  // Letters from the coding manual; G-series plates (GT, GN, GW, GE, GC...) are Greater Accra.
  // Motorbike plates "M-20-AS 1234" use the letters after the year.
  var PLATE = { AS: "1", BA: "2", CR: "3", ER: "4", GR: "5", NR: "6", UE: "7", UW: "8", VR: "9",
                WR: "10", GA: "11", GP: "11" };
  function plateCode(text) {
    var t = (text || "").toUpperCase().replace(/^M-?\d{2}-?/, "").replace(/[^A-Z0-9]/g, " ").trim();
    var m = /^([A-Z]{2})\b|^([A-Z]{2})\d/.exec(t);
    var letters = m && (m[1] || m[2]);
    if (!letters) return "";
    if (PLATE[letters]) return PLATE[letters];
    if (/^G[TNWECSBXM]$/.test(letters)) return "5";
    return "";
  }
  form.addEventListener("input", function (ev) {
    if (!/-registration_no$/.test(ev.target.name || "")) return;
    var card = ev.target.closest(".vehicle");
    var code = card && card.querySelector('[name$="-registration_code"]');
    if (!code || (code.value && !code.dataset.auto)) return;      // never overwrite a choice
    var guess = plateCode(ev.target.value);
    code.value = guess;
    if (guess) code.dataset.auto = "1"; else delete code.dataset.auto;
  });
  form.addEventListener("change", function (ev) {
    if (/-registration_code$/.test(ev.target.name || "")) delete ev.target.dataset.auto;
  });

  function refresh(firstRun) {
    applyAllRules(firstRun === true);
    showTables();
    if (killed && injured && severity) countPeople();
  }
  form.addEventListener("change", function (ev) {
    // The question a follow-up depends on was changed: saved follow-ups may now be hidden.
    if (/(road_description|shoulder_type|vehicle_type|licence_status)$/.test(ev.target.name || "")) {
      var card = ev.target.closest(".vehicle");
      (card || form).querySelectorAll(".field[data-kept]").forEach(function (box) {
        if (card || !box.closest(".vehicle")) box.removeAttribute("data-kept");
      });
    }
    refresh();
  });
  form.addEventListener("input", refresh);
  form.addEventListener("click", function () { setTimeout(refresh, 0); });   // add / remove rows
  refresh(true);
})();
