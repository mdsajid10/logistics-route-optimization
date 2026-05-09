const API_BASE = window.location.origin.startsWith("http")
  ? window.location.origin
  : "http://127.0.0.1:8000";

const uploadBtn = document.getElementById("uploadBtn");
const runBtn = document.getElementById("runBtn");
const csvFileInput = document.getElementById("csvFile");
const statusText = document.getElementById("statusText");
const resultsTableBody = document.querySelector("#resultsTable tbody");
const bestSuggestion = document.getElementById("bestSuggestion");
const loader = document.getElementById("loader");
const routeStopsList = document.getElementById("routeStopsList");
const routeSearchInput = document.getElementById("routeSearchInput");
const copyRouteBtn = document.getElementById("copyRouteBtn");
const downloadRouteBtn = document.getElementById("downloadRouteBtn");
const simulateBtn = document.getElementById("simulateBtn");
const simulatorStatus = document.getElementById("simulatorStatus");
const simulatorSection = document.getElementById("simulatorSection");
const advicePanel = document.getElementById("advicePanel");
const adviceContent = document.getElementById("adviceContent");
const simDelivered = document.getElementById("simDelivered");
const simPending = document.getElementById("simPending");
const simElapsed = document.getElementById("simElapsed");
const simPhase = document.getElementById("simPhase");
const simEventLog = document.getElementById("simEventLog");
const speedSignal = document.getElementById("speedSignal");
const pauseSimBtn = document.getElementById("pauseSimBtn");
const followBikeChk = document.getElementById("followBikeChk");
const simTraffic = document.getElementById("simTraffic");

document.documentElement.lang = "en";
if (typeof Chart !== "undefined") {
  Chart.defaults.locale = "en-US";
  Chart.defaults.font.family = "Arial";
  Chart.defaults.color = "#d8f6ff";
}

function formatEn(value, digits = 4) {
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

let map;
let markersLayer;
let routeLayers = [];
let chartRefs = [];
let currentBestRoute = null;
let simulationActive = false;
let simulationMarker = null;
let simulationSpeed = 1.0;
let simulationRunId = 0;
let simulationSummary = null;
let simulationTrailLayer = null;
let simulationPaused = false;

function setupMap() {
  map = L.map("map").setView([20.5937, 78.9629], 5);

  // Street layer
  const streetLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  });

  // Satellite layer (Esri World Imagery)
  const satelliteLayer = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      attribution: "&copy; Esri",
      maxZoom: 18,
    }
  );

  // Dark layer (CartoDB)
  const darkLayer = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    {
      attribution: "&copy; CartoDB",
      maxZoom: 19,
    }
  );

  // Add satellite layer by default
  satelliteLayer.addTo(map);

  // Layer control
  const baseLayers = {
    "Street Map": streetLayer,
    "🛰️ Satellite": satelliteLayer,
    "Dark Map": darkLayer,
  };

  L.control.layers(baseLayers).addTo(map);

  markersLayer = L.layerGroup().addTo(map);
}

function setLoading(isLoading) {
  loader.classList.toggle("hidden", !isLoading);
  uploadBtn.disabled = isLoading;
  runBtn.disabled = isLoading || runBtn.dataset.ready !== "true";
}

function setStatus(message) {
  statusText.textContent = message;
}

async function uploadCsv() {
  const file = csvFileInput.files[0];
  if (!file) {
    setStatus("Select a CSV file first.");
    return;
  }

  const fd = new FormData();
  fd.append("file", file);

  setLoading(true);
  setStatus("Uploading CSV and parsing coordinates...");

  try {
    const response = await fetch(`${API_BASE}/upload-csv`, {
      method: "POST",
      body: fd,
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Upload failed");
    }

    runBtn.disabled = false;
    runBtn.dataset.ready = "true";
    setStatus(`Loaded ${payload.node_count} locations. Ready to run optimization.`);
  } catch (err) {
    setStatus(`Upload error: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

function clearRouteLayers() {
  routeLayers.forEach((layer) => map.removeLayer(layer));
  routeLayers = [];
  markersLayer.clearLayers();
  routeStopsList.innerHTML = "";
  currentBestRoute = null;
  copyRouteBtn.disabled = true;
  downloadRouteBtn.disabled = true;
  simulationActive = false;
  simulationRunId += 1;
  if (simulationMarker) {
    map.removeLayer(simulationMarker);
    simulationMarker = null;
  }
  if (simulationTrailLayer) {
    map.removeLayer(simulationTrailLayer);
    simulationTrailLayer = null;
  }
  simulateBtn.disabled = true;
  pauseSimBtn.disabled = true;
  pauseSimBtn.textContent = "Pause";
  simulateBtn.textContent = "Start Bike Simulation";
}

function renderRouteStops(bestRoute, searchText = "") {
  routeStopsList.innerHTML = "";
  const stops = bestRoute?.route_stops || [];
  const query = (searchText || "").trim().toLowerCase();

  const filteredStops = query
    ? stops.filter((stop) => {
      const haystack = `${stop.order_id} ${Number(stop.latitude).toFixed(5)} ${Number(stop.longitude).toFixed(5)}`.toLowerCase();
      return haystack.includes(query);
    })
    : stops;

  if (filteredStops.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No matching stops found.";
    routeStopsList.appendChild(li);
    return;
  }

  filteredStops.forEach((stop) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="stop-order">${stop.order_id}</span>
      <span class="stop-coords">(${formatEn(stop.latitude, 5)}, ${formatEn(stop.longitude, 5)})</span>
    `;
    routeStopsList.appendChild(li);
  });
}

async function copyRouteToClipboard() {
  if (!currentBestRoute?.route_stops?.length) {
    return;
  }

  const lines = [
    "Optimized Bike Route",
    ...currentBestRoute.route_stops.map((stop) => `${stop.sequence}. ${stop.order_id} (${formatEn(stop.latitude, 5)}, ${formatEn(stop.longitude, 5)})`),
  ];

  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    setStatus("Optimized route copied to clipboard.");
  } catch {
    setStatus("Could not copy route. Please try again.");
  }
}

function downloadRouteCsv() {
  if (!currentBestRoute?.route_stops?.length) {
    return;
  }

  const header = "sequence,order_id,latitude,longitude";
  const rows = currentBestRoute.route_stops.map((stop) =>
    `${stop.sequence},${stop.order_id},${Number(stop.latitude).toFixed(6)},${Number(stop.longitude).toFixed(6)}`,
  );
  const csv = [header, ...rows].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "optimized_bike_route.csv";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
  setStatus("Optimized route CSV downloaded.");
}

function drawRoutes(results, bestByCost) {
  clearRouteLayers();

  const colorMap = {
    "GA": "#2457ff",
    "ACO": "#2a9d8f",
    "Hybrid GA-ACO": "#e63946",
  };

  const bestRoute = results.find((row) => row.algorithm === bestByCost) || results[0];
  if (!bestRoute) {
    return;
  }
  currentBestRoute = bestRoute;
  copyRouteBtn.disabled = false;
  downloadRouteBtn.disabled = false;

  const polyline = L.polyline(bestRoute.route_points, {
    color: colorMap[bestRoute.algorithm] || "#111",
    weight: 4,
    opacity: 0.95,
  }).addTo(map);

  polyline.bindPopup(`Optimized: ${bestRoute.algorithm}<br/>Distance: ${bestRoute.distance_km} km`);
  routeLayers.push(polyline);

  const routeStops = bestRoute.route_stops || [];
  routeStops.forEach((stop) => {
    const point = [stop.latitude, stop.longitude];
    L.circleMarker(point, {
      radius: 5,
      color: "#172a3a",
      fillColor: "#fff",
      fillOpacity: 0.9,
      weight: 1,
    })
      .bindTooltip(`${stop.sequence}. ${stop.order_id}`)
      .addTo(markersLayer);
  });

  renderRouteStops(bestRoute, routeSearchInput.value);

  if (bestRoute.route_points.length > 1) {
    map.fitBounds(bestRoute.route_points, { padding: [24, 24] });
  }
}

function renderTable(resultPayload) {
  const {
    results,
    best_by_distance,
    best_by_cost,
    distance_mode_effective,
    distance_fallback_used,
  } = resultPayload;
  resultsTableBody.innerHTML = "";

  results.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.algorithm === best_by_cost) {
      tr.classList.add("best");
    }

    tr.innerHTML = `
      <td>${row.algorithm}</td>
      <td>${formatEn(row.distance_km, 4)}</td>
      <td>${formatEn(row.eta_hours, 4)}</td>
      <td>${formatEn(row.fuel_cost, 4)}</td>
      <td>${formatEn(row.objective, 4)}</td>
      <td>${formatEn(row.route_efficiency_pct, 2)}</td>
    `;

    resultsTableBody.appendChild(tr);
  });

  const modeLabel = distance_mode_effective === "road_bike"
    ? "Road distance (bike)"
    : (distance_mode_effective === "road_car"
      ? "Road distance (car)"
      : (distance_mode_effective === "road_walk" ? "Road distance (walk)" : "Straight-line distance"));

  const fallbackText = distance_fallback_used ? " | Fallback active" : "";
  bestSuggestion.textContent = `Best by objective cost: ${best_by_cost} | Best by distance: ${best_by_distance} | Mode: ${modeLabel}${fallbackText}`;
}

function destroyCharts() {
  chartRefs.forEach((c) => c.destroy());
  chartRefs = [];
}

function createBarGradient(ctx, colorStops) {
  const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
  colorStops.forEach(([offset, color]) => gradient.addColorStop(offset, color));
  return gradient;
}

const ALGO_COLORS = {
  "GA": { from: "#4f8cff", to: "#1b3fa0", border: "#6ea8ff", glow: "rgba(79,140,255,0.35)" },
  "ACO": { from: "#34d4b0", to: "#0f7c6a", border: "#5ae8c8", glow: "rgba(52,212,176,0.35)" },
  "Hybrid GA-ACO": { from: "#ff6b7a", to: "#b02a37", border: "#ff99a5", glow: "rgba(255,107,122,0.35)" },
};

function getAlgoColor(algoName, ctx) {
  const c = ALGO_COLORS[algoName] || ALGO_COLORS["GA"];
  return {
    bg: createBarGradient(ctx, [[0, c.from], [1, c.to]]),
    border: c.border,
    glow: c.glow,
  };
}

function makeBarChart(canvasId, title, values, labels) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext("2d");

  const bgColors = labels.map((l) => getAlgoColor(l, ctx).bg);
  const borderColors = labels.map((l) => getAlgoColor(l, ctx).border);
  const hoverBgColors = labels.map((l) => getAlgoColor(l, ctx).border);

  return new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: title,
        data: values,
        backgroundColor: bgColors,
        borderColor: borderColors,
        borderWidth: 1.5,
        borderRadius: { topLeft: 8, topRight: 8 },
        borderSkipped: false,
        hoverBackgroundColor: hoverBgColors,
        hoverBorderWidth: 2,
        barPercentage: 0.62,
        categoryPercentage: 0.7,
      }],
    },
    plugins: [{
      id: "valueLabels",
      afterDatasetsDraw(chart) {
        const { ctx: c } = chart;
        chart.data.datasets.forEach((dataset, di) => {
          const meta = chart.getDatasetMeta(di);
          meta.data.forEach((bar, i) => {
            const val = dataset.data[i];
            const text = Number(val) >= 100 ? formatEn(val, 1) : formatEn(val, 2);
            c.save();
            c.font = "bold 11px 'Space Grotesk', sans-serif";
            c.fillStyle = "#ffffff";
            c.textAlign = "center";
            c.textBaseline = "bottom";
            c.shadowColor = "rgba(0,0,0,0.55)";
            c.shadowBlur = 4;
            c.fillText(text, bar.x, bar.y - 6);
            c.restore();
          });
        });
      },
    }, {
      id: "barGlow",
      afterDatasetsDraw(chart) {
        const { ctx: c } = chart;
        chart.data.datasets.forEach((dataset, di) => {
          const meta = chart.getDatasetMeta(di);
          meta.data.forEach((bar, i) => {
            const algoName = chart.data.labels[i];
            const glow = (ALGO_COLORS[algoName] || ALGO_COLORS["GA"]).glow;
            c.save();
            c.shadowColor = glow;
            c.shadowBlur = 14;
            c.fillStyle = "rgba(0,0,0,0)";
            c.fillRect(bar.x - bar.width / 2, bar.y, bar.width, 2);
            c.restore();
          });
        });
      },
    }],
    options: {
      locale: "en-US",
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        duration: 900,
        easing: "easeOutQuart",
      },
      layout: {
        padding: { top: 24, bottom: 4, left: 6, right: 6 },
      },
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: title,
          color: "#c8eeff",
          font: { family: "'Orbitron', sans-serif", size: 12, weight: 600 },
          padding: { top: 2, bottom: 12 },
        },
        tooltip: {
          backgroundColor: "rgba(6,22,38,0.92)",
          titleColor: "#8ae5ff",
          bodyColor: "#e9fbff",
          borderColor: "rgba(93,220,255,0.35)",
          borderWidth: 1,
          cornerRadius: 8,
          padding: 10,
          titleFont: { family: "'Orbitron', sans-serif", size: 11, weight: 600 },
          bodyFont: { family: "'Space Grotesk', sans-serif", size: 12.5 },
          callbacks: {
            title: (items) => items[0].label,
            label: (context) => `${title}: ${formatEn(context.parsed.y, 4)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          border: { display: false },
          ticks: {
            color: "#8cbcd0",
            font: { family: "'Space Grotesk', sans-serif", size: 11, weight: 600 },
            padding: 6,
          },
        },
        y: {
          beginAtZero: true,
          grid: {
            color: "rgba(93,220,255,0.08)",
            lineWidth: 0.8,
          },
          border: { display: false },
          ticks: {
            color: "#6faabb",
            font: { family: "'Space Grotesk', sans-serif", size: 10.5 },
            padding: 8,
            callback: (value) => Number(value).toLocaleString("en-US"),
            maxTicksLimit: 6,
          },
        },
      },
    },
  });
}

function renderCharts(results) {
  destroyCharts();

  const labels = results.map((r) => r.algorithm);
  const distances = results.map((r) => r.distance_km);
  const times = results.map((r) => r.eta_hours);
  const fuel = results.map((r) => r.fuel_cost);

  chartRefs.push(makeBarChart("distanceChart", "Distance (km)", distances, labels));
  chartRefs.push(makeBarChart("timeChart", "ETA (hours)", times, labels));
  chartRefs.push(makeBarChart("fuelChart", "Fuel Cost (₹)", fuel, labels));
}

async function runOptimization() {
  setLoading(true);
  setStatus("Running GA, ACO, and Hybrid optimization...");

  try {
    const response = await fetch(`${API_BASE}/run-algorithms`);
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || "Optimization failed");
    }

    renderTable(payload);
    drawRoutes(payload.results, payload.best_by_cost);
    renderCharts(payload.results);

    const bestByDistanceRow = payload.results.find((r) => r.algorithm === payload.best_by_distance);
    const bestByCostRow = payload.results.find((r) => r.algorithm === payload.best_by_cost);
    const tieHint = bestByDistanceRow && bestByCostRow
      && Math.abs(Number(bestByDistanceRow.eta_hours) - Number(bestByCostRow.eta_hours)) < 1e-6
      ? " | Note: equal ETA means routes have effectively same travel time"
      : "";

    setStatus(`Done. Baseline distance: ${payload.baseline_distance_km} km | Mode: ${payload.distance_mode_effective}${tieHint}`);

    // Show simulator section
    simulatorSection.classList.remove("hidden");
    simulateBtn.disabled = false;
    simulateBtn.textContent = "Start Bike Simulation";
  } catch (err) {
    setStatus(`Run error: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// Motorcycle SVG Icon
function createMotorcycleIcon() {
  const bikeImageSvg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
      <defs>
        <linearGradient id="bikeBody" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#ff7a2f"/>
          <stop offset="100%" stop-color="#ffb347"/>
        </linearGradient>
      </defs>
      <circle cx="32" cy="88" r="18" fill="none" stroke="#f8e2a4" stroke-width="6"/>
      <circle cx="96" cy="88" r="18" fill="none" stroke="#f8e2a4" stroke-width="6"/>
      <path d="M44 88 L62 62 L84 62 L96 88" fill="none" stroke="#ffe08c" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M62 62 L52 46 L70 46 L80 62" fill="url(#bikeBody)" stroke="#ffd58a" stroke-width="3" stroke-linejoin="round"/>
      <path d="M70 46 L86 40" stroke="#ffd58a" stroke-width="4" stroke-linecap="round"/>
      <circle cx="62" cy="62" r="4" fill="#fff0ba"/>
      <ellipse cx="60" cy="42" rx="8" ry="4" fill="#ffe9a9"/>
    </svg>
  `.trim();

  return L.icon({
    iconUrl: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(bikeImageSvg)}`,
    iconSize: [46, 46],
    iconAnchor: [23, 23],
    popupAnchor: [0, -18],
    className: "motorcycle-image-icon",
  });
}

// Simulator functions
function updateSimulatorStatus(message) {
  simulatorStatus.textContent = message;
  simulatorStatus.classList.add("pulse-animate");
  setTimeout(() => simulatorStatus.classList.remove("pulse-animate"), 600);
}

function generateAdvice(route) {
  const distanceSuggestion = route.distance_km > 100
    ? `Consider breaking this ${formatEn(route.distance_km, 2)}km route into multiple days`
    : `This ${formatEn(route.distance_km, 2)}km route is optimal for single-day delivery`;

  const etaSuggestion = route.eta_hours > 8
    ? `⏱️ ETA of ${formatEn(route.eta_hours, 2)} hours exceeds standard 8-hour shift. Suggest two riders or split delivery.`
    : `✓ ETA of ${formatEn(route.eta_hours, 2)} hours fits within standard working hours`;

  const efficiencySuggestion = route.route_efficiency_pct > 85
    ? `🎯 Excellent efficiency (${formatEn(route.route_efficiency_pct, 1)}%) - route is well optimized`
    : `📊 Efficiency is ${formatEn(route.route_efficiency_pct, 1)}% - Consider alternative route planning`;

  const projectedHours = Number(route.eta_hours);
  const simulatedHours = simulationSummary ? (simulationSummary.simulatedMinutes / 60) : projectedHours;
  const deltaHours = simulatedHours - projectedHours;
  const deltaText = deltaHours > 0
    ? `Simulation indicates +${formatEn(deltaHours, 2)} hours over projected ETA due to stop servicing and traffic fluctuation.`
    : `Simulation indicates ${formatEn(Math.abs(deltaHours), 2)} hours faster than projected ETA under current speed profile.`;

  return `
    <div class="advice-item">
      <div class="advice-title">🚗 Delivery Strategy</div>
      <p>${distanceSuggestion}</p>
    </div>
    <div class="advice-item">
      <div class="advice-title">⏰ Time Management</div>
      <p>${etaSuggestion}</p>
    </div>
    <div class="advice-item">
      <div class="advice-title">⚙️ Route Quality</div>
      <p>${efficiencySuggestion}</p>
    </div>
    <div class="advice-item">
      <div class="advice-title">💡 Recommended Changes</div>
      <p>${deltaText}<br/>Current simulated time: <strong>${formatEn(simulatedHours, 2)} hours</strong> → Suggested target: <strong>${formatEn(Math.max(projectedHours * 0.95, 0.1), 2)} hours</strong> with staggered dispatch windows.</p>
    </div>
  `;
}

function resetSimulationDashboard(totalStops) {
  if (simDelivered) simDelivered.textContent = "0%";
  if (simPending) simPending.textContent = `0/${totalStops}`;
  if (simElapsed) simElapsed.textContent = "0.0 km";
  if (simPhase) simPhase.textContent = "0.0 km";
  if (simTraffic) simTraffic.textContent = "Normal";
  if (simEventLog) simEventLog.innerHTML = "";
}

function appendSimulationEvent(message) {
  if (!simEventLog) return;
  const li = document.createElement("li");
  li.textContent = message;
  simEventLog.prepend(li);
  while (simEventLog.children.length > 7) {
    simEventLog.removeChild(simEventLog.lastChild);
  }
}

function updateSimulationDashboard(progressPct, checkpointText, traveledKm, remainingKm) {
  if (simDelivered) simDelivered.textContent = `${formatEn(progressPct, 1)}%`;
  if (simPending) simPending.textContent = checkpointText;
  if (simElapsed) simElapsed.textContent = `${formatEn(traveledKm, 2)} km`;
  if (simPhase) simPhase.textContent = `${formatEn(Math.max(remainingKm, 0), 2)} km`;
}

function waitMs(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getSegmentLengthKm(a, b) {
  if (!map || !map.distance) {
    return 0;
  }
  return map.distance(a, b) / 1000;
}

function getPointAtDistance(points, segmentMeta, distanceKm) {
  if (points.length < 2) {
    return points[0];
  }

  const clamped = Math.max(0, Math.min(distanceKm, segmentMeta.totalKm));

  for (let i = 0; i < segmentMeta.items.length; i += 1) {
    const seg = segmentMeta.items[i];
    if (clamped <= seg.endKm || i === segmentMeta.items.length - 1) {
      const local = seg.lengthKm > 0 ? (clamped - seg.startKm) / seg.lengthKm : 0;
      const lat = seg.from[0] + (seg.to[0] - seg.from[0]) * local;
      const lng = seg.from[1] + (seg.to[1] - seg.from[1]) * local;
      return [lat, lng];
    }
  }

  return points[points.length - 1];
}

function buildSegmentMeta(points) {
  const items = [];
  let cumulative = 0;

  for (let i = 0; i < points.length - 1; i += 1) {
    const from = points[i];
    const to = points[i + 1];
    const lengthKm = getSegmentLengthKm(from, to);
    items.push({
      from,
      to,
      lengthKm,
      startKm: cumulative,
      endKm: cumulative + lengthKm,
    });
    cumulative += lengthKm;
  }

  return {
    items,
    totalKm: cumulative,
  };
}

async function runSimulation() {
  if (!currentBestRoute || !currentBestRoute.route_points) {
    updateSimulatorStatus("❌ No route data available");
    return;
  }

  if (simulationActive) {
    simulationActive = false;
    simulationPaused = false;
    simulationRunId += 1;
    simulateBtn.textContent = "Start Bike Simulation";
    pauseSimBtn.disabled = true;
    pauseSimBtn.textContent = "Pause";
    if (simulationMarker) {
      map.removeLayer(simulationMarker);
      simulationMarker = null;
    }
    if (simulationTrailLayer) {
      map.removeLayer(simulationTrailLayer);
      simulationTrailLayer = null;
    }
    updateSimulatorStatus("Simulation stopped.");
    return;
  }

  simulationActive = true;
  simulationPaused = false;
  simulationRunId += 1;
  const runId = simulationRunId;
  simulateBtn.textContent = "Stop Simulation";
  pauseSimBtn.disabled = false;
  pauseSimBtn.textContent = "Pause";
  advicePanel.classList.add("hidden");
  adviceContent.innerHTML = "";

  const routePoints = currentBestRoute.route_points || [];
  const routeStops = currentBestRoute.route_stops || [];

  if (routePoints.length < 2 || routeStops.length < 1) {
    simulationActive = false;
    simulateBtn.textContent = "Start Bike Simulation";
    updateSimulatorStatus("❌ Route data is incomplete for simulation.");
    return;
  }

  updateSimulatorStatus("Starting bike route simulation...");
  resetSimulationDashboard(routeStops.length);
  appendSimulationEvent(`Bike locked to optimized route with ${routeStops.length} checkpoints.`);

  if (simulationTrailLayer) {
    map.removeLayer(simulationTrailLayer);
  }
  simulationTrailLayer = L.polyline([routePoints[0]], {
    color: "#ffc048",
    weight: 6,
    opacity: 0.85,
  }).addTo(map);

  // Create motorcycle marker
  simulationMarker = L.marker(routePoints[0], {
    icon: createMotorcycleIcon(),
    zIndexOffset: 1000,
  }).addTo(map);

  map.flyTo(routePoints[0], 15, { animate: true, duration: 1 });
  await waitMs(900);

  if (!simulationActive || runId !== simulationRunId) {
    return;
  }

  const segmentMeta = buildSegmentMeta(routePoints);
  const totalKm = Math.max(segmentMeta.totalKm, Number(currentBestRoute.distance_km) || 0.01);
  const maxSimulatorMinutes = Math.max(1, Number(currentBestRoute.eta_hours || 1) * 60 / simulationSpeed);
  const totalDurationMs = Math.max(6000, totalKm * 7000 / simulationSpeed);
  let startedAt = performance.now();
  let lastCheckpoint = 0;
  let lastPanTime = 0;
  const checkpointPauseBaseMs = 1400;

  while (simulationActive && runId === simulationRunId) {
    if (simulationPaused) {
      const pausedAt = performance.now();
      await waitMs(60);
      if (!simulationPaused) {
        startedAt += performance.now() - pausedAt;
      }
      continue;
    }

    const elapsedMs = performance.now() - startedAt;
    const ratio = Math.min(1, elapsedMs / totalDurationMs);
    const distanceKm = totalKm * ratio;
    const point = getPointAtDistance(routePoints, segmentMeta, distanceKm);

    if (simulationMarker) {
      simulationMarker.setLatLng(point);
    }

    if (followBikeChk && followBikeChk.checked && map) {
      const now = performance.now();
      if (now - lastPanTime > 280) {
        map.panTo(point, { animate: false });
        lastPanTime = now;
      }
    }

    if (simulationTrailLayer) {
      const currentTrail = simulationTrailLayer.getLatLngs();
      currentTrail.push(point);
      simulationTrailLayer.setLatLngs(currentTrail);
    }

    const progress = ratio * 100;
    const checkpoint = Math.min(routeStops.length, Math.floor(ratio * routeStops.length));
    const checkpointText = `${checkpoint}/${routeStops.length}`;
    const remainingKm = totalKm - distanceKm;
    updateSimulationDashboard(progress, checkpointText, distanceKm, remainingKm);
    updateSimulatorStatus(`Bike is following route path: ${formatEn(progress, 1)}% complete.`);

    const trafficFactor = 1 + (Math.sin((ratio * 12) + 0.9) * 0.15 + 0.12);
    if (simTraffic) {
      if (trafficFactor > 1.18) {
        simTraffic.textContent = "Heavy";
      } else if (trafficFactor > 1.08) {
        simTraffic.textContent = "Moderate";
      } else {
        simTraffic.textContent = "Normal";
      }
    }

    if (checkpoint > lastCheckpoint && checkpoint <= routeStops.length && checkpoint > 0) {
      const stop = routeStops[checkpoint - 1];
      appendSimulationEvent(`Reached checkpoint ${checkpoint}: ${stop.order_id}`);
      lastCheckpoint = checkpoint;

      // Wait at each delivery point
      const pauseMs = checkpointPauseBaseMs / simulationSpeed;
      updateSimulatorStatus(`At ${stop.order_id}: delivery handoff in progress...`);
      appendSimulationEvent(`Waiting ${(pauseMs / 1000).toFixed(1)}s at ${stop.order_id} for delivery confirmation.`);
      const waitStart = performance.now();
      const waitUntil = waitStart + pauseMs;
      while (simulationActive && runId === simulationRunId && performance.now() < waitUntil) {
        if (simulationPaused) {
          const pausedAt = performance.now();
          await waitMs(60);
          if (!simulationPaused) {
            startedAt += performance.now() - pausedAt;
          }
          continue;
        }
        await waitMs(60);
      }
      startedAt += performance.now() - waitStart;
      if (!simulationActive || runId !== simulationRunId) {
        return;
      }
    }

    if (ratio >= 1) {
      break;
    }

    await waitMs(35);
  }

  if (!simulationActive || runId !== simulationRunId) {
    return;
  }

  simulationActive = false;
  simulationPaused = false;
  simulateBtn.textContent = "Start Bike Simulation";
  pauseSimBtn.disabled = true;
  pauseSimBtn.textContent = "Pause";
  updateSimulationDashboard(100, `${routeStops.length}/${routeStops.length}`, totalKm, 0);
  simulationSummary = {
    delivered: routeStops.length,
    pending: 0,
    simulatedMinutes: maxSimulatorMinutes,
    projectedMinutes: Number(currentBestRoute.eta_hours || 0) * 60,
  };

  updateSimulatorStatus("Bike completed the full optimized path. Generating route advice...");
  appendSimulationEvent(`Completed full path: ${formatEn(totalKm, 2)} km across ${routeStops.length} checkpoints.`);
  advicePanel.classList.remove("hidden");
  adviceContent.innerHTML = generateAdvice(currentBestRoute);
}

// Speed control
const speedSlowBtn = document.getElementById("speedSlowBtn");
const speedNormalBtn = document.getElementById("speedNormalBtn");
const speedFastBtn = document.getElementById("speedFastBtn");

function setSimulationSpeed(multiplier, button) {
  simulationSpeed = multiplier;
  [speedSlowBtn, speedNormalBtn, speedFastBtn].forEach((btn) => {
    btn.classList.remove("active");
  });
  button.classList.add("active");

  if (!speedSignal) {
    return;
  }

  if (multiplier <= 0.5) {
    speedSignal.textContent = "Speed Signal: 🐢 Slow";
  } else if (multiplier >= 2.0) {
    speedSignal.textContent = "Speed Signal: ⚡ Fast";
  } else {
    speedSignal.textContent = "Speed Signal: 🏍️ Normal";
  }
}

function togglePauseSimulation() {
  if (!simulationActive) {
    return;
  }
  simulationPaused = !simulationPaused;
  pauseSimBtn.textContent = simulationPaused ? "Resume" : "Pause";
  updateSimulatorStatus(simulationPaused ? "Simulation paused." : "Simulation resumed.");
}

uploadBtn.addEventListener("click", uploadCsv);
runBtn.addEventListener("click", runOptimization);
routeSearchInput.addEventListener("input", () => {
  renderRouteStops(currentBestRoute, routeSearchInput.value);
});
copyRouteBtn.addEventListener("click", copyRouteToClipboard);
downloadRouteBtn.addEventListener("click", downloadRouteCsv);
simulateBtn.addEventListener("click", runSimulation);
pauseSimBtn.addEventListener("click", togglePauseSimulation);

speedSlowBtn.addEventListener("click", () => setSimulationSpeed(10.0, speedSlowBtn));
speedNormalBtn.addEventListener("click", () => setSimulationSpeed(20.0, speedNormalBtn));
speedFastBtn.addEventListener("click", () => setSimulationSpeed(50.0, speedFastBtn));

setSimulationSpeed(1.0, speedNormalBtn);

setupMap();

