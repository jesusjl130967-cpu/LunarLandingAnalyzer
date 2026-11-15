(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const form = $("#missionForm");
  const globe = $("#lunarGlobe");
  const globeContext = globe.getContext("2d");
  let catalog = [];
  let currentResult = null;
  let timelinePoints = [];
  let playTimer = null;
  let previewTimer = null;
  let globeYaw = 0.35;
  let globePitch = -0.12;
  let globeZoom = 1;
  let globePointer = null;

  function makeCraters() {
    let seed = 39173;
    const random = () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    return Array.from({ length: 960 }, () => ({
      latitude: Math.asin(2 * random() - 1) * 180 / Math.PI,
      longitude: random() * 360 - 180,
      size: 0.003 + random() ** 2 * 0.065,
      depth: 0.18 + random() * 0.32
    }));
  }
  const surfaceCraters = makeCraters();
  const majorCraters = [
    { latitude: -89.5, longitude: 0, size: 0.045 },
    { latitude: -82, longitude: 27, size: 0.035 },
    { latitude: -77, longitude: -35, size: 0.027 },
    { latitude: 52, longitude: -4, size: 0.034 },
    { latitude: 17, longitude: -5, size: 0.025 }
  ];
  const lowAlbedoPatches = [
    { latitude: 18, longitude: -57, size: 0.16 },
    { latitude: 32, longitude: -15, size: 0.13 },
    { latitude: 28, longitude: 18, size: 0.11 },
    { latitude: 8, longitude: 31, size: 0.09 },
    { latitude: 17, longitude: 59, size: 0.08 },
    { latitude: -21, longitude: -16, size: 0.09 },
    { latitude: -24, longitude: -39, size: 0.08 },
    { latitude: -5, longitude: 53, size: 0.08 }
  ];
  const lunarTexture = createLunarTexture();
  let surfaceCanvas;
  let surfaceContext;

  function makeNoiseGrid(width, height, initialSeed) {
    let seed = initialSeed;
    const values = new Float32Array(width * height);
    for (let index = 0; index < values.length; index += 1) {
      seed = (seed * 16807) % 2147483647;
      values[index] = (seed - 1) / 2147483646;
    }
    return { width, height, values };
  }

  function sampleNoise(grid, u, v) {
    const x = u * grid.width;
    const y = Math.max(0, Math.min(grid.height - 1, v * (grid.height - 1)));
    const x0 = Math.floor(x) % grid.width;
    const x1 = (x0 + 1) % grid.width;
    const y0 = Math.floor(y);
    const y1 = Math.min(grid.height - 1, y0 + 1);
    const tx = (x - Math.floor(x)) ** 2 * (3 - 2 * (x - Math.floor(x)));
    const rawTy = y - y0;
    const ty = rawTy * rawTy * (3 - 2 * rawTy);
    const top = grid.values[y0 * grid.width + x0] * (1 - tx) + grid.values[y0 * grid.width + x1] * tx;
    const bottom = grid.values[y1 * grid.width + x0] * (1 - tx) + grid.values[y1 * grid.width + x1] * tx;
    return top * (1 - ty) + bottom * ty;
  }

  function createLunarTexture() {
    const width = 768;
    const height = 384;
    const size = width * height;
    const broadNoise = makeNoiseGrid(32, 16, 21891);
    const mediumNoise = makeNoiseGrid(112, 56, 73921);
    const fineNoise = makeNoiseGrid(384, 192, 15413);
    const relief = new Float32Array(size);
    const image = new ImageData(width, height);
    const allCraters = [
      ...surfaceCraters,
      ...majorCraters.map((crater) => ({ ...crater, depth: 0.92 }))
    ];

    for (let y = 0; y < height; y += 1) {
      const v = y / (height - 1);
      const latitude = (0.5 - v) * Math.PI;
      for (let x = 0; x < width; x += 1) {
        const u = x / width;
        const longitude = (u - 0.5) * Math.PI * 2;
        let tone = 174 +
          (sampleNoise(broadNoise, u, v) - 0.5) * 24 +
          (sampleNoise(mediumNoise, u, v) - 0.5) * 19 +
          (sampleNoise(fineNoise, u, v) - 0.5) * 22;

        for (const patch of lowAlbedoPatches) {
          const centerLat = patch.latitude * Math.PI / 180;
          const centerLon = patch.longitude * Math.PI / 180;
          const deltaLon = Math.atan2(Math.sin(longitude - centerLon), Math.cos(longitude - centerLon)) * Math.cos(centerLat);
          const deltaLat = latitude - centerLat;
          const distance = (deltaLon / (patch.size * 1.3)) ** 2 + (deltaLat / patch.size) ** 2;
          if (distance < 4) tone -= 27 * Math.exp(-distance * 0.85);
        }
        relief[y * width + x] = tone;
      }
    }

    for (const crater of allCraters) {
      const latitude = crater.latitude * Math.PI / 180;
      const centerX = ((crater.longitude + 180) / 360) * width;
      const centerY = (0.5 - crater.latitude / 180) * height;
      const angularRadius = crater.size * 1.35;
      const radiusX = Math.max(2, Math.ceil(angularRadius * width / (2 * Math.PI * Math.max(0.12, Math.cos(latitude)))));
      const radiusY = Math.max(2, Math.ceil(angularRadius * height / Math.PI));

      for (let offsetY = -radiusY; offsetY <= radiusY; offsetY += 1) {
        const y = Math.round(centerY) + offsetY;
        if (y < 0 || y >= height) continue;
        for (let offsetX = -radiusX; offsetX <= radiusX; offsetX += 1) {
          const normalizedX = offsetX / radiusX;
          const normalizedY = offsetY / radiusY;
          const distance = Math.sqrt(normalizedX * normalizedX + normalizedY * normalizedY);
          if (distance > 1.28) continue;
          let x = Math.round(centerX) + offsetX;
          x = (x % width + width) % width;
          const bowl = Math.max(0, 1 - distance / 0.78);
          const rimDistance = (distance - 0.84) / 0.12;
          const rim = Math.exp(-(rimDistance * rimDistance));
          const ejecta = Math.max(0, 1 - Math.abs(distance - 1.08) / 0.2);
          relief[y * width + x] += crater.depth * (-16 * bowl + 22 * rim + 4 * ejecta);
        }
      }
    }

    for (let index = 0; index < size; index += 1) {
      const tone = Math.max(112, Math.min(232, relief[index]));
      const pixel = index * 4;
      image.data[pixel] = Math.min(255, tone + 2);
      image.data[pixel + 1] = Math.min(255, tone + 1);
      image.data[pixel + 2] = Math.max(0, tone - 3);
      image.data[pixel + 3] = 255;
    }
    return image;
  }

  function renderLunarSurface(metrics) {
    const diameter = Math.max(2, Math.ceil(metrics.radius * 2));
    if (!surfaceCanvas) {
      surfaceCanvas = document.createElement("canvas");
      surfaceContext = surfaceCanvas.getContext("2d", { alpha: true });
    }
    if (surfaceCanvas.width !== diameter || surfaceCanvas.height !== diameter) {
      surfaceCanvas.width = diameter;
      surfaceCanvas.height = diameter;
    }

    const image = surfaceContext.createImageData(diameter, diameter);
    const output = image.data;
    const texture = lunarTexture.data;
    const textureWidth = lunarTexture.width;
    const textureHeight = lunarTexture.height;
    const cosineYaw = Math.cos(globeYaw);
    const sineYaw = Math.sin(globeYaw);
    const cosinePitch = Math.cos(globePitch);
    const sinePitch = Math.sin(globePitch);
    const solarVector = currentResult?.solar?.sun_vector_lunar;

    for (let y = 0; y < diameter; y += 1) {
      const viewY = 1 - 2 * (y + 0.5) / diameter;
      for (let x = 0; x < diameter; x += 1) {
        const viewX = 2 * (x + 0.5) / diameter - 1;
        const radiusSquared = viewX * viewX + viewY * viewY;
        if (radiusSquared >= 1) continue;

        const viewZ = Math.sqrt(1 - radiusSquared);
        const pitchY = viewY * cosinePitch + viewZ * sinePitch;
        const pitchZ = -viewY * sinePitch + viewZ * cosinePitch;
        const bodyX = viewX * cosineYaw + pitchZ * sineYaw;
        const bodyY = pitchY;
        const bodyZ = -viewX * sineYaw + pitchZ * cosineYaw;
        const latitude = Math.asin(Math.max(-1, Math.min(1, bodyY)));
        const longitude = Math.atan2(bodyX, bodyZ);
        const textureX = ((longitude / (2 * Math.PI) + 0.5) * textureWidth) % textureWidth;
        const textureY = (0.5 - latitude / Math.PI) * (textureHeight - 1);
        const x0 = Math.floor(textureX);
        const x1 = (x0 + 1) % textureWidth;
        const y0 = Math.floor(textureY);
        const y1 = Math.min(textureHeight - 1, y0 + 1);
        const tx = textureX - x0;
        const ty = textureY - y0;
        const topLeft = (y0 * textureWidth + x0) * 4;
        const topRight = (y0 * textureWidth + x1) * 4;
        const bottomLeft = (y1 * textureWidth + x0) * 4;
        const bottomRight = (y1 * textureWidth + x1) * 4;
        const top = texture[topLeft] * (1 - tx) + texture[topRight] * tx;
        const bottom = texture[bottomLeft] * (1 - tx) + texture[bottomRight] * tx;
        const tone = top * (1 - ty) + bottom * ty;
        const directLight = solarVector
          ? Math.max(0, bodyX * solarVector[0] + bodyY * solarVector[1] + bodyZ * solarVector[2])
          : 0.6;
        const shade = (0.045 + 0.955 * directLight) * (0.88 + 0.12 * viewZ);
        const pixel = (y * diameter + x) * 4;
        output[pixel] = (tone + 2) * shade;
        output[pixel + 1] = (tone + 1) * shade;
        output[pixel + 2] = (tone - 3) * shade;
        output[pixel + 3] = 255;
      }
    }

    surfaceContext.putImageData(image, 0, 0);
    return surfaceCanvas;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
  }

  function missionPayload() {
    const raw = $("#missionTime").value;
    return {
      mission_name: $("#missionName").value.trim(),
      site_id: $("#siteSelect").value,
      latitude: Number($("#latitude").value),
      longitude: Number($("#longitude").value),
      mission_time: raw ? `${raw}:00Z` : ""
    };
  }

  async function api(url, body) {
    const options = body ? {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    } : {};
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Error HTTP ${response.status}`);
    return data;
  }

  function formatCoord(lat, lon) {
    return `${Math.abs(lat).toFixed(2)}° ${lat < 0 ? "S" : "N"}, ${lon.toFixed(2)}°`;
  }

  function rotateGlobePoint(latitude, longitude) {
    const lat = latitude * Math.PI / 180;
    const lon = longitude * Math.PI / 180;
    const x = Math.cos(lat) * Math.sin(lon);
    const y = Math.sin(lat);
    const z = Math.cos(lat) * Math.cos(lon);
    const yawX = x * Math.cos(globeYaw) - z * Math.sin(globeYaw);
    const yawZ = x * Math.sin(globeYaw) + z * Math.cos(globeYaw);
    return {
      x: yawX,
      y: y * Math.cos(globePitch) - yawZ * Math.sin(globePitch),
      z: y * Math.sin(globePitch) + yawZ * Math.cos(globePitch)
    };
  }

  function globeMetrics() {
    const bounds = globe.getBoundingClientRect();
    const width = bounds.width;
    const height = bounds.height;
    return {
      width,
      height,
      centerX: width * 0.5,
      centerY: height * 0.51,
      radius: Math.min(width * 0.31, height * 0.43) * globeZoom
    };
  }

  function projectGlobePoint(latitude, longitude, metrics) {
    const point = rotateGlobePoint(latitude, longitude);
    return {
      ...point,
      x: metrics.centerX + point.x * metrics.radius,
      y: metrics.centerY - point.y * metrics.radius
    };
  }

  function drawGlobeLine(points, metrics, color, width) {
    globeContext.beginPath();
    let drawing = false;
    for (const [latitude, longitude] of points) {
      const point = projectGlobePoint(latitude, longitude, metrics);
      if (point.z > 0.001) {
        if (!drawing) globeContext.moveTo(point.x, point.y);
        else globeContext.lineTo(point.x, point.y);
        drawing = true;
      } else {
        drawing = false;
      }
    }
    globeContext.strokeStyle = color;
    globeContext.lineWidth = width;
    globeContext.stroke();
  }

  function updateSelectedMarker() {
    const lat = Number($("#latitude").value);
    const lon = Number($("#longitude").value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
    $("#mapCoords").textContent = formatCoord(lat, lon);
    $("#globeCalloutCoord").textContent = `${formatCoord(lat, lon).replace(", ", " · ")}`;
    const selectedSite = catalog.find((site) => site.id === $("#siteSelect").value);
    $("#globeSiteName").textContent = (selectedSite?.name || "COORDENADAS PERSONALIZADAS")
      .replace(/^(Borde del cráter |Región de )/, "")
      .split(" (")[0]
      .toLocaleUpperCase("es");
    drawGlobe();
  }

  function drawGlobe() {
    const bounds = globe.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const pixelRatio = window.devicePixelRatio || 1;
    const pixelWidth = Math.round(bounds.width * pixelRatio);
    const pixelHeight = Math.round(bounds.height * pixelRatio);
    if (globe.width !== pixelWidth || globe.height !== pixelHeight) {
      globe.width = pixelWidth;
      globe.height = pixelHeight;
    }
    globeContext.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    globeContext.clearRect(0, 0, bounds.width, bounds.height);
    const metrics = globeMetrics();
    const { centerX, centerY, radius } = metrics;
    const sphere = new Path2D();
    sphere.arc(centerX, centerY, radius, 0, Math.PI * 2);

    globeContext.save();
    globeContext.shadowColor = "#d9d4c04d";
    globeContext.shadowBlur = 24;
    globeContext.fillStyle = "#262a2d";
    globeContext.fill(sphere);
    globeContext.restore();
    globeContext.drawImage(renderLunarSurface(metrics), centerX - radius, centerY - radius, radius * 2, radius * 2);
    globeContext.save();
    globeContext.clip(sphere);

    for (const latitude of [-60, -30, 0, 30, 60]) {
      const points = [];
      for (let longitude = -180; longitude <= 180; longitude += 4) points.push([latitude, longitude]);
      drawGlobeLine(points, metrics, "rgba(245, 239, 226, .055)", 0.55);
    }
    for (let longitude = -150; longitude <= 180; longitude += 30) {
      const points = [];
      for (let latitude = -88; latitude <= 88; latitude += 3) points.push([latitude, longitude]);
      drawGlobeLine(points, metrics, "rgba(245, 239, 226, .045)", 0.5);
    }

    const selected = {
      latitude: Number($("#latitude").value),
      longitude: Number($("#longitude").value),
      id: $("#siteSelect").value,
      name: catalog.find((site) => site.id === $("#siteSelect").value)?.name || "Coordenadas personalizadas",
      kind: "selected"
    };
    const sites = [...catalog];
    if (!sites.some((site) => site.id === selected.id)) sites.push(selected);
    let selectedVisible = false;
    for (const site of sites) {
      const point = projectGlobePoint(site.latitude, site.longitude, metrics);
      if (point.z <= 0.001) continue;
      const isSelected = site.id === selected.id ||
        (selected.id === "custom" && site.latitude === selected.latitude && site.longitude === selected.longitude);
      if (isSelected) selectedVisible = true;
      const color = isSelected ? "#fffdf4" : (site.kind === "historical" ? "#c6c6bf" : "#e5b968");
      const markerRadius = isSelected ? 5.2 : 3.8;
      globeContext.beginPath();
      globeContext.arc(point.x, point.y, markerRadius + (isSelected ? 4 : 0), 0, Math.PI * 2);
      globeContext.fillStyle = isSelected ? "#e5b96858" : "#282923";
      globeContext.fill();
      globeContext.beginPath();
      globeContext.arc(point.x, point.y, markerRadius, 0, Math.PI * 2);
      globeContext.fillStyle = color;
      globeContext.strokeStyle = "#3e3a32";
      globeContext.lineWidth = 1.3;
      globeContext.fill();
      globeContext.stroke();
      if (isSelected) {
        globeContext.font = "10px system-ui, sans-serif";
        const label = site.name.replace(/^(Borde del cráter |Región de )/, "").split(" (")[0];
        const labelWidth = globeContext.measureText(label).width;
        const labelX = point.x + labelWidth + 16 > metrics.width - 6 ? point.x - 8 : point.x + 8;
        globeContext.textAlign = labelX < point.x ? "right" : "left";
        globeContext.fillStyle = "#fbf6e8";
        globeContext.shadowColor = "#171614";
        globeContext.shadowBlur = 4;
        const labelY = point.y > centerY + radius * 0.62 ? point.y - 16 : point.y - 7;
        globeContext.fillText(label, labelX, labelY);
        globeContext.shadowBlur = 0;
      }
    }
    globeContext.restore();
    $("#globeCallout").classList.toggle("hidden", !selectedVisible);
    globeContext.beginPath();
    globeContext.arc(centerX, centerY, radius, 0, Math.PI * 2);
    globeContext.strokeStyle = "#e5e2d96e";
    globeContext.lineWidth = 1.1;
    globeContext.stroke();
    $("#globeStatus").textContent = selectedVisible
      ? "HEMISFERIO VISIBLE · SITIO EN CARA FRONTAL"
      : "HEMISFERIO VISIBLE · SITIO EN CARA OCULTA";
  }

  function selectGlobeLocation(event) {
    const bounds = globe.getBoundingClientRect();
    const metrics = globeMetrics();
    const x = (event.clientX - bounds.left - metrics.centerX) / metrics.radius;
    const y = -(event.clientY - bounds.top - metrics.centerY) / metrics.radius;
    const radiusSquared = x * x + y * y;
    if (radiusSquared > 1) return;
    const z = Math.sqrt(1 - radiusSquared);
    const pitchY = y * Math.cos(globePitch) + z * Math.sin(globePitch);
    const pitchZ = -y * Math.sin(globePitch) + z * Math.cos(globePitch);
    const bodyX = x * Math.cos(globeYaw) + pitchZ * Math.sin(globeYaw);
    const bodyZ = -x * Math.sin(globeYaw) + pitchZ * Math.cos(globeYaw);
    const latitude = Math.asin(Math.max(-1, Math.min(1, pitchY))) * 180 / Math.PI;
    const longitude = Math.atan2(bodyX, bodyZ) * 180 / Math.PI;

    const site = catalog.find((item) => {
      const point = projectGlobePoint(item.latitude, item.longitude, metrics);
      return point.z > 0.001 && Math.hypot(point.x - (event.clientX - bounds.left), point.y - (event.clientY - bounds.top)) < 13;
    });
    if (site) {
      selectSite(site.id);
      return;
    }
    $("#siteSelect").value = "custom";
    $("#latitude").value = latitude.toFixed(4);
    $("#longitude").value = longitude.toFixed(4);
    updateSelectedMarker();
    if (currentResult) refreshPreview();
  }

  function changeGlobeZoom(amount) {
    globeZoom = Math.max(0.82, Math.min(2.15, globeZoom + amount));
    drawGlobe();
  }

  function selectSite(id) {
    $("#siteSelect").value = id;
    const site = catalog.find((item) => item.id === id);
    if (!site) return;
    $("#latitude").value = site.latitude;
    $("#longitude").value = site.longitude;
    updateSelectedMarker();
    if (currentResult) refreshPreview();
  }

  function populateSites() {
    const select = $("#siteSelect");
    select.replaceChildren();
    const groups = [
      ["candidate", "Regiones de referencia · demostración"],
      ["historical", "Sitios históricos"]
    ];
    for (const [kind, label] of groups) {
      const group = document.createElement("optgroup");
      group.label = label;
      for (const site of catalog.filter((item) => item.kind === kind)) {
        const option = document.createElement("option");
        option.value = site.id;
        option.textContent = site.name;
        group.append(option);
      }
      select.append(group);
    }
    const custom = document.createElement("option");
    custom.value = "custom";
    custom.textContent = "Coordenadas personalizadas";
    select.append(custom);
    select.value = catalog[0]?.id || "custom";
    selectSite(select.value);
    const checks = $("#comparisonSites");
    checks.replaceChildren();
    for (const site of catalog) {
      const label = document.createElement("label");
      label.className = "check-site";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = site.id;
      input.checked = site.kind === "candidate";
      label.append(input, document.createTextNode(site.name));
      checks.append(label);
    }
    drawGlobe();
  }

  function chartSvg(points, compact = false) {
    if (!points.length) return "";
    const width = 760;
    const height = compact ? 150 : 215;
    const left = 42, right = 12, top = 14, bottom = 25;
    const plotW = width - left - right, plotH = height - top - bottom;
    const temperatures = points.map((point) => point.temperature_c);
    const minTemp = Math.min(-250, Math.floor(Math.min(...temperatures) / 20) * 20);
    const maxTemp = Math.max(20, Math.ceil(Math.max(...temperatures) / 20) * 20);
    const x = (index) => left + index / Math.max(1, points.length - 1) * plotW;
    const yTemp = (value) => top + (maxTemp - value) / (maxTemp - minTemp) * plotH;
    const ySun = (value) => top + (90 - Math.max(-90, Math.min(90, value))) / 180 * plotH;
    const grid = [];
    for (let i = 0; i <= 4; i++) {
      const val = minTemp + (maxTemp - minTemp) * i / 4;
      const y = yTemp(val);
      grid.push(`<line class="chart-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"/><text class="chart-label" x="${left - 7}" y="${y + 3}" text-anchor="end">${Math.round(val)}°</text>`);
    }
    const tempPath = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${yTemp(point.temperature_c).toFixed(1)}`).join(" ");
    const sunPath = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${ySun(point.sun_elevation_deg).toFixed(1)}`).join(" ");
    const sunAxis = [-90, 0, 90].map((value) => {
      const y = ySun(value);
      return `<text class="chart-label" x="${width - right + 5}" y="${y + 3}" text-anchor="start">${value}°</text>`;
    }).join("");
    const tickIndices = [...new Set([0, Math.round((points.length - 1) / 4), Math.round((points.length - 1) / 2), Math.round((points.length - 1) * 3 / 4), points.length - 1])];
    const ticks = tickIndices.map((index) => `<text class="chart-label" x="${x(index)}" y="${height - 5}" text-anchor="middle">+${index * 2}h</text>`).join("");
    const circles = points.map((point, index) => `<circle cx="${x(index)}" cy="${yTemp(point.temperature_c)}" r="${point.sunlit ? 1.8 : 1.3}" fill="${point.sunlit ? "#61d9e4" : "#7e91a1"}"/>`).join("");
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Temperatura estimada e iluminación durante 72 horas">${grid.join("")}<line class="chart-axis" x1="${left}" y1="${top}" x2="${left}" y2="${height - bottom}"/><path class="temp-line" d="${tempPath}"/><path class="sun-line" d="${sunPath}"/>${circles}${sunAxis}${ticks}<text class="chart-label" x="${width - right}" y="${top + 7}" text-anchor="end">— Temperatura · - - Elevación solar</text></svg>`;
  }

  function windowsSvg(points) {
    if (!points.length) return "";
    const width = 760, height = 150, left = 32, right = 10, top = 12, bottom = 24;
    const step = (width - left - right) / points.length;
    const plotH = height - top - bottom;
    const bars = points.map((point, index) => {
      const barH = Math.max(2, point.score / 100 * plotH);
      return `<rect class="window-bar ${point.score < 55 ? "low" : ""}" x="${left + index * step}" y="${top + plotH - barH}" width="${Math.max(1, step - 1)}" height="${barH}" rx="1"><title>${new Date(point.time).toLocaleString("es", { timeZone: "UTC" })} UTC · ${point.score}/100</title></rect>`;
    }).join("");
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Puntuación orientativa de ventanas próximas">${[0, 50, 100].map((v) => {
      const y = top + plotH - v / 100 * plotH;
      return `<line class="chart-grid" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"/><text class="chart-label" x="${left - 5}" y="${y + 3}" text-anchor="end">${v}</text>`;
    }).join("")}${bars}<text class="chart-label" x="${left}" y="${height - 5}">Hoy</text><text class="chart-label" x="${width - right}" y="${height - 5}" text-anchor="end">+30 días</text></svg>`;
  }

  function renderEnergy(thermal) {
    $("#energyDiagram").innerHTML = `<div class="energy-box"><span>ABSORBIDA · superficie</span><b>${thermal.absorbed_w_m2.toFixed(1)} W/m²</b></div><div class="energy-box emit"><span>EMITIDA · equilibrio</span><b>${thermal.emitted_w_m2.toFixed(1)} W/m²</b></div><div class="energy-line"></div>`;
    $("#energyDetails").innerHTML = `<span>Radiación solar incidente <b>${thermal.incident_w_m2.toFixed(1)} W/m²</b></span><span>Albedo utilizado <b>${(thermal.albedo * 100).toFixed(0)}%</b></span><span>Emisividad térmica <b>${thermal.emissivity.toFixed(2)}</b></span><span>Equilibrio radiativo <b>${thermal.equilibrium_k.toFixed(1)} K / ${thermal.equilibrium_c.toFixed(1)} °C</b></span>`;
  }

  function renderDiagnostic(verdict) {
    const list = (items) => items.length ? `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<p>Ningún factor registrado.</p>";
    $("#diagnosticContent").innerHTML = `<div class="diagnostic-content"><h4>Factores favorables</h4><div class="good">${list(verdict.favorable)}</div><h4>Riesgos a revisar</h4><div class="risk">${list(verdict.risks)}</div><h4>Información faltante</h4><div>${list(verdict.missing)}</div></div>`;
  }

  function renderIntegrations(status) {
    if (!status) return;
    const label = (item) => item.available === true
      ? "Disponible"
      : item.available === false ? "Respaldo local" : "Bajo demanda";
    $("#integrationStatus").innerHTML = ["horizons", "pds", "spice"].map((key) => {
      const item = status[key];
      return `<span><b>${escapeHtml(item.source)} · ${label(item)}</b><br>${escapeHtml(item.message)}</span>`;
    }).join("");
  }

  function secureLink(value, label) {
    try {
      const url = new URL(value);
      if (url.protocol === "https:") return `<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    } catch (error) {
      return "";
    }
    return "";
  }

  async function searchProducts() {
    const button = $("#searchProductsButton");
    const output = $("#productResults");
    button.disabled = true;
    button.textContent = "Buscando en PDS ODE…";
    output.textContent = "Consultando cobertura de productos Diviner y LOLA para las coordenadas seleccionadas.";
    try {
      const data = await api("/api/data-products", {
        latitude: Number($("#latitude").value),
        longitude: Number($("#longitude").value)
      });
      const groups = data.results.map((group) => {
        const products = group.products.length
          ? `<ul>${group.products.map((item) => {
            const links = [
              secureLink(item.product_url, "Ficha"),
              secureLink(item.label_url, "Etiqueta"),
              secureLink(item.files_url, "Archivos")
            ].filter(Boolean).join(" · ");
            return `<li><b>${escapeHtml(item.product_id)}</b>${item.observation_time ? ` · ${escapeHtml(item.observation_time)}` : ""}${item.description ? `<p>${escapeHtml(item.description.slice(0, 240))}</p>` : ""}${links ? `<p>${links}</p>` : ""}</li>`;
          }).join("")}</ul>`
          : "<p>ODE no devolvió productos para esta cobertura.</p>";
        return `<div class="product-group"><h3>${escapeHtml(group.instrument)} · ${group.available ? `${group.products.length} producto(s) devuelto(s)` : "sin respuesta"}</h3><p>${escapeHtml(group.message)}</p>${products}</div>`;
      }).join("");
      const area = data.search_area;
      output.innerHTML = `${groups}<div class="product-footnote">Caja consultada: latitud ${area.latitude_min}° a ${area.latitude_max}°, longitud ${area.longitude_west}° a ${area.longitude_east}°. ${escapeHtml(data.limitations)}</div>`;
    } catch (error) {
      output.textContent = error.message;
    } finally {
      button.disabled = false;
      button.innerHTML = 'Buscar productos LRO en esta zona <span>→</span>';
    }
  }

  function renderSolarTelemetry(solar, illumination, thermal) {
    if (!solar || !illumination) return;
    $("#illuminationValue").textContent = illumination.state;
    $("#sunElevation").textContent = `Elevación solar ${illumination.sun_elevation_deg.toFixed(2)}°`;
    $("#sunHours").textContent = `${illumination.sunlight_hours_30d.toFixed(1)} h de luz / próximos 30 días`;
    $("#temperatureBar").style.width = `${Math.max(0, Math.min(100, illumination.sunlight_hours_30d / 7.2))}%`;
    $("#globalLitArea").textContent = `${solar.global_illuminated_surface_percent.toFixed(1)}%`;
    $("#globalDarkArea").textContent = `${solar.global_dark_surface_percent.toFixed(1)}%`;
    $("#visibleDiskIllumination").textContent = `${solar.visible_disk_illuminated_percent.toFixed(1)}%`;
    $("#solarE0").textContent = `${solar.solar_irradiance_w_m2.toFixed(1)} W/m²`;
    $("#solarDistance").textContent = `${solar.sun_moon_distance_km.toLocaleString("es")} km`;
    $("#solarSubpoint").textContent = `${solar.subsolar_latitude_deg.toFixed(2)}°, ${solar.subsolar_longitude_deg.toFixed(2)}°`;
    $("#solarIncidence").textContent = `${illumination.incidence_angle_deg.toFixed(2)}° · μ ${illumination.mu.toFixed(4)}`;
    $("#localIrradiance").textContent = `${illumination.incident_irradiance_w_m2.toFixed(1)} W/m²`;
    $("#reflectedFlux").textContent = `${illumination.reflected_flux_w_m2.toFixed(1)} W/m²`;
    $("#topographicShadow").textContent = illumination.topographic_shadow === null ? "Sin evaluar · sin DEM" : (illumination.topographic_shadow ? "En sombra" : "Sin sombra");
    $("#telemetrySun").textContent = `${illumination.sun_elevation_deg.toFixed(2)}°`;
    $("#telemetryIllumination").textContent = illumination.state;
    if (thermal) {
      $("#thermalIncident").textContent = `${thermal.incident_w_m2.toFixed(1)} W/m²`;
      $("#thermalAbsorbed").textContent = `${thermal.absorbed_w_m2.toFixed(1)} W/m²`;
      $("#thermalEmitted").textContent = `${thermal.emitted_w_m2.toFixed(1)} W/m²`;
      $("#temperatureValue").textContent = `${thermal.temperature_c.toFixed(1)} °C`;
      $("#thermalModel").textContent = `${thermal.equilibrium_k.toFixed(1)} K · ${thermal.model}`;
      renderEnergy(thermal);
    }
    drawGlobe();
  }

  function renderResult(result, persisted = Boolean(result.evaluation_id)) {
    currentResult = result;
    $("#emptyState").classList.add("hidden");
    $("#results").classList.remove("hidden");
    const missionDate = new Date(result.mission_time_utc);
    const dateLabel = missionDate.toLocaleString("es", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" });
    const coordinates = formatCoord(result.site.latitude, result.site.longitude);
    $("#analysisTime").textContent = `${dateLabel} UTC`;
    $("#missionDisplayName").textContent = result.mission_name.toLocaleUpperCase("es");
    $("#missionNameBadge").textContent = result.mission_name.toLocaleUpperCase("es");
    $("#missionMeta").textContent = `${result.site.name} · ${coordinates} · ${dateLabel} UTC`;
    $("#globeSiteName").textContent = result.site.name.replace(/^(Borde del cráter |Región de )/, "").split(" (")[0].toLocaleUpperCase("es");
    $("#globeCalloutCoord").textContent = coordinates.replace(", ", " · ");
    $("#temperatureValue").textContent = `${result.thermal.temperature_c.toFixed(1)} °C`;
    $("#thermalModel").textContent = `${result.thermal.equilibrium_k.toFixed(1)} K · ${result.thermal.model}`;
    $("#communicationValue").textContent = result.communication.earth_visible ? "Visible" : "Oculta";
    $("#earthElevation").textContent = `Elevación geométrica ${result.communication.earth_elevation_deg.toFixed(2)}°`;
    $("#relayValue").textContent = result.communication.relay_recommended ? "Evaluar relé de comunicaciones" : "Geometría favorable; enlace no garantizado";
    $("#telemetryTemperature").textContent = `${result.thermal.temperature_c.toFixed(1)} °C`;
    $("#telemetryComm").textContent = result.communication.earth_visible ? "Sí · geométrica" : "No · bajo horizonte";
    $("#telemetrySlope").textContent = result.terrain.slope_deg === null ? "Sin DEM" : `${result.terrain.slope_deg.toFixed(1)}° · referencia`;
    $("#telemetryLatitude").textContent = `${Math.abs(result.site.latitude).toFixed(3)}° ${result.site.latitude < 0 ? "S" : "N"}`;
    $("#telemetryLongitude").textContent = `${Math.abs(result.site.longitude).toFixed(3)}° ${result.site.longitude < 0 ? "W" : "E"}`;
    $("#telemetryDate").textContent = missionDate.toLocaleString("es", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" }) + " UTC";
    const verdictCard = $(".status-card");
    verdictCard.dataset.state = result.verdict.label;
    $("#verdictValue").textContent = result.verdict.label;
    $("#verdictSummary").textContent = result.verdict.summary;
    $("#siteScience").textContent = `${result.science} Fuente del sitio: ${catalog.find((item) => item.id === result.site.id)?.source || "entrada del usuario"} · ${result.sources.diviner}.`;
    renderIntegrations(result.integrations);
    renderSolarTelemetry(result.solar, result.illumination, result.thermal);
    renderDiagnostic(result.verdict);
    for (const [id, extension] of [["pdfLink", "pdf"], ["csvLink", "csv"]]) {
      const link = $(`#${id}`);
      if (persisted) {
        link.href = `/report/${result.evaluation_id}.${extension}`;
        link.classList.remove("disabled");
        link.setAttribute("aria-disabled", "false");
      } else {
        link.href = "#";
        link.classList.add("disabled");
        link.setAttribute("aria-disabled", "true");
      }
    }
    loadTimeline();
    loadWindows();
    if (persisted) loadHistory();
  }

  async function evaluate(event) {
    if (event) event.preventDefault();
    const button = $("#evaluateButton");
    const message = $("#formMessage");
    message.textContent = "";
    button.disabled = true;
    button.querySelector("span").textContent = "Calculando…";
    try {
      const result = await api("/api/analyze", missionPayload());
      renderResult(result, true);
      message.textContent = "Evaluación calculada y guardada localmente.";
    } catch (error) {
      message.textContent = error.message;
    } finally {
      button.disabled = false;
      button.querySelector("span").textContent = "Evaluar sitio de aterrizaje";
    }
  }

  async function loadTimeline() {
    if (!currentResult) return;
    try {
      const data = await api("/api/timeline", missionPayload());
      timelinePoints = data.points;
      $("#timelineChart").innerHTML = chartSvg(timelinePoints);
      $("#timelineSlider").value = 0;
      setTimelineOffset(0);
    } catch (error) {
      $("#timelineChart").textContent = error.message;
    }
  }

  async function loadWindows() {
    if (!currentResult) return;
    try {
      const data = await api("/api/windows", missionPayload());
      $("#windowsChart").innerHTML = windowsSvg(data.points);
    } catch (error) {
      $("#windowsChart").textContent = error.message;
    }
  }

  function setTimelineOffset(value) {
    const offset = Number(value);
    $("#timelineOffset").textContent = `T + ${String(offset).padStart(2, "0")} h`;
    const point = timelinePoints.find((item) => new Date(item.time).getTime() === new Date(missionPayload().mission_time).getTime() + offset * 3600000);
    if (point) {
      const illumination = {
        ...currentResult.illumination,
        mu: point.mu,
        state: point.sunlit ? (point.mu < 0.05 ? "Iluminación rasante" : "Iluminado") : "En sombra",
        sunlit: point.sunlit,
        sun_elevation_deg: point.sun_elevation_deg,
        incidence_angle_deg: point.incidence_angle_deg,
        incident_irradiance_w_m2: point.incident_irradiance_w_m2,
        reflected_flux_w_m2: point.reflected_flux_w_m2
      };
      const thermal = {
        ...currentResult.thermal,
        incident_w_m2: point.incident_irradiance_w_m2,
        absorbed_w_m2: point.absorbed_w_m2,
        emitted_w_m2: point.emitted_w_m2,
        equilibrium_k: point.equilibrium_k,
        temperature_k: point.equilibrium_k,
        temperature_c: point.temperature_c,
        equilibrium_c: point.temperature_c,
        solar_irradiance_w_m2: point.solar.solar_irradiance_w_m2
      };
      currentResult.solar = point.solar;
      renderSolarTelemetry(point.solar, illumination, thermal);
      $("#telemetryTemperature").textContent = `${point.temperature_c.toFixed(1)} °C`;
      $("#telemetryDate").textContent = new Date(point.time).toLocaleString("es", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" }) + " UTC";
      $("#analysisTime").textContent = new Date(point.time).toLocaleString("es", { timeZone: "UTC", dateStyle: "medium", timeStyle: "short" }) + " UTC";
      $("#communicationValue").textContent = point.earth_visible ? "Visible" : "Oculta";
    }
  }

  async function loadHistory() {
    try {
      const rows = await api("/api/history");
      const container = $("#historyList");
      if (!rows.length) {
        container.innerHTML = '<div class="history-empty">Todavía no hay evaluaciones guardadas.</div>';
        return;
      }
      container.innerHTML = rows.map((row) => `<div class="history-row"><div>${escapeHtml(row.mission_name)}<small>${escapeHtml(row.site_name)}</small></div><div>${Number(row.latitude).toFixed(2)}°, ${Number(row.longitude).toFixed(2)}°</div><div>${new Date(row.mission_time).toLocaleString("es", { timeZone: "UTC", dateStyle: "short", timeStyle: "short" })} UTC</div><div class="history-links"><a href="/report/${row.id}.pdf">PDF</a><a href="/report/${row.id}.csv">CSV</a></div></div>`).join("");
    } catch (error) {
      $("#historyList").innerHTML = `<div class="history-empty">${escapeHtml(error.message)}</div>`;
    }
  }

  async function compareSelected() {
    const ids = [...$("#comparisonSites").querySelectorAll('input:checked')].map((input) => input.value);
    if (ids.length < 2) {
      $("#comparisonOutput").innerHTML = "Selecciona al menos dos sitios.";
      $("#comparisonOutput").classList.remove("hidden");
      return;
    }
    const button = $("#compareButton");
    button.disabled = true;
    try {
      const data = await api("/api/compare", { ...missionPayload(), site_ids: ids });
      $("#comparisonOutput").innerHTML = `<table class="comparison-table"><thead><tr><th>SITIO</th><th>TEMP.</th><th>ELEV. SOLAR</th><th>LUZ / 30 D</th><th>TIERRA VISIBLE</th><th>PENDIENTE</th><th>CRIBADO</th></tr></thead><tbody>${data.sites.map((site) => `<tr><td>${escapeHtml(site.name)}</td><td>${site.temperature_c.toFixed(1)} °C</td><td>${site.sun_elevation_deg.toFixed(1)}°</td><td>${site.sunlight_hours_30d.toFixed(0)} h</td><td>${site.earth_visible ? "Sí" : "No"}</td><td>${site.slope_deg === null ? "Sin DEM" : `${site.slope_deg.toFixed(1)}°`}</td><td>${escapeHtml(site.verdict)}</td></tr>`).join("")}</tbody></table><div class="map-footnote">Horizons/SPICE se aplican al instante evaluado; la curva de 30 días es analítica. No se procesan productos Diviner/LOLA ni sombras DEM.</div>`;
      $("#comparisonOutput").classList.remove("hidden");
    } catch (error) {
      $("#comparisonOutput").textContent = error.message;
      $("#comparisonOutput").classList.remove("hidden");
    } finally {
      button.disabled = false;
    }
  }

  function setClock() {
    $("#clock").textContent = new Date().toLocaleTimeString("es", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  }

  function bindEvents() {
    form.addEventListener("submit", evaluate);
    $("#searchProductsButton").addEventListener("click", searchProducts);
    $("#siteSelect").addEventListener("change", (event) => selectSite(event.target.value));
    for (const field of [$("#latitude"), $("#longitude")]) {
      field.addEventListener("input", () => {
        $("#siteSelect").value = "custom";
        updateSelectedMarker();
        window.clearTimeout(previewTimer);
        previewTimer = window.setTimeout(() => {
          if (currentResult) refreshPreview();
        }, 250);
      });
    }
    globe.addEventListener("pointerdown", (event) => {
      globePointer = {
        x: event.clientX,
        y: event.clientY,
        startX: event.clientX,
        startY: event.clientY,
        moved: false
      };
      globe.setPointerCapture(event.pointerId);
      globe.classList.add("dragging");
    });
    globe.addEventListener("pointermove", (event) => {
      if (!globePointer) return;
      const bounds = globe.getBoundingClientRect();
      const dx = event.clientX - globePointer.x;
      const dy = event.clientY - globePointer.y;
      if (Math.hypot(event.clientX - globePointer.startX, event.clientY - globePointer.startY) > 3) globePointer.moved = true;
      globePointer.x = event.clientX;
      globePointer.y = event.clientY;
      globeYaw += dx / Math.max(80, bounds.height * .43 * globeZoom);
      globePitch = Math.max(-1.35, Math.min(1.35, globePitch + dy / Math.max(80, bounds.height * .43 * globeZoom)));
      drawGlobe();
    });
    globe.addEventListener("pointerup", (event) => {
      if (globePointer && !globePointer.moved) selectGlobeLocation(event);
      globePointer = null;
      globe.classList.remove("dragging");
    });
    globe.addEventListener("pointercancel", () => {
      globePointer = null;
      globe.classList.remove("dragging");
    });
    globe.addEventListener("wheel", (event) => {
      event.preventDefault();
      changeGlobeZoom(event.deltaY < 0 ? .12 : -.12);
    }, { passive: false });
    $("#zoomIn").addEventListener("click", () => changeGlobeZoom(.25));
    $("#zoomOut").addEventListener("click", () => changeGlobeZoom(-.25));
    $("#zoomReset").addEventListener("click", () => {
      globeYaw = .35;
      globePitch = -.12;
      globeZoom = 1;
      drawGlobe();
    });
    window.addEventListener("resize", drawGlobe);
    $("#compareButton").addEventListener("click", compareSelected);
    $("#timelineSlider").addEventListener("input", (event) => setTimelineOffset(event.target.value));
    $("#timelineBack").addEventListener("click", () => {
      const slider = $("#timelineSlider");
      slider.value = Math.max(0, Number(slider.value) - 12);
      setTimelineOffset(slider.value);
    });
    $("#timelinePlay").addEventListener("click", (event) => {
      if (playTimer) {
        clearInterval(playTimer);
        playTimer = null;
        event.currentTarget.textContent = "▶ Reproducir";
      } else {
        event.currentTarget.textContent = "Ⅱ Pausar";
        playTimer = setInterval(() => {
          const slider = $("#timelineSlider");
          slider.value = Number(slider.value) >= 72 ? 0 : Number(slider.value) + 2;
          setTimelineOffset(slider.value);
        }, 500);
      }
    });
    $("#missionTime").addEventListener("change", () => {
      if (currentResult) refreshPreview();
    });
    $("#siteSelect").addEventListener("change", () => {
      if (currentResult) refreshPreview();
    });
    $("#missionName").addEventListener("input", (event) => {
      const label = event.target.value.trim() || "Lunar Survey";
      $("#missionDisplayName").textContent = label.toLocaleUpperCase("es");
      $("#missionNameBadge").textContent = label.toLocaleUpperCase("es");
    });
    document.querySelectorAll("[data-telemetry-tab]").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll("[data-telemetry-tab]").forEach((item) => {
          const active = item === tab;
          item.classList.toggle("active", active);
          item.setAttribute("aria-selected", String(active));
        });
        document.querySelectorAll("[data-telemetry-pane]").forEach((pane) => {
          pane.classList.toggle("active", pane.dataset.telemetryPane === tab.dataset.telemetryTab);
        });
      });
    });
    document.querySelectorAll(".side-nav a").forEach((link) => {
      link.addEventListener("click", () => {
        document.querySelectorAll(".side-nav a").forEach((item) => item.classList.toggle("active", item === link));
      });
    });
  }

  async function refreshPreview() {
    try {
      const result = await api("/api/preview", missionPayload());
      renderResult(result, false);
    } catch (error) {
      $("#formMessage").textContent = error.message;
    }
  }

  async function init() {
    bindEvents();
    setClock();
    window.setInterval(setClock, 30000);
    try {
      catalog = await api("/api/sites");
      populateSites();
      drawGlobe();
      await loadHistory();
      await refreshPreview();
    } catch (error) {
      $("#formMessage").textContent = `No se pudo cargar el catálogo local: ${error.message}`;
    }
  }

  init();
})();
