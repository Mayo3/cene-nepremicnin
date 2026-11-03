// Map of sold buildings. map.json: {paths, buildings: [[lon, lat, path index, address, [[day, 0 flat / 1 house, m², €], ...]], ...]}.
// A building's dot is coloured by the median €/m² of its sales that match the filters.
(() => {
  const el = document.getElementById("map");
  if (!el || !window.maplibregl) return;
  const BINS = [1500, 2500, 3500, 4500, 5500];                                 // kept in step with MAP_BINS in build.py
  const COLORS = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
  const kindBox = document.getElementById("kind");
  const periodBox = document.getElementById("period");
  const count = document.getElementById("count");
  const eur = (x) => Math.round(x).toLocaleString("sl-SI") + " €";
  const date = (d) => d.split("-").reverse().map(Number).join(". ");
  const median = (v) => { v.sort((a, b) => a - b); const h = v.length >> 1; return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2; };

  const map = new maplibregl.Map({
    container: el, style: "https://tiles.openfreemap.org/styles/positron", hash: true,
    center: [14.85, 46.12], zoom: 7.4, minZoom: 6.5, maxBounds: [[12.4, 44.9], [17.4, 47.3]],
    customAttribution: 'Prodaje: <a href="https://www.e-prostor.gov.si/">GURS, ETN</a> (CC BY 4.0)',
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  map.addControl(new maplibregl.GeolocateControl({ fitBoundsOptions: { maxZoom: 15 } }));
  const loading = fetch("/map.json").then((r) => r.json());
  let data;

  function matching(b) {
    const kind = kindBox.value, period = periodBox.value;
    return b[4].filter((s) => (kind === "" || s[1] === +kind) &&
      (period === "" || (period === "12" ? s[0] >= data.since : s[0].startsWith(period))));
  }

  function features() {
    const out = [];
    data.buildings.forEach((b, i) => {
      const v = matching(b).map((s) => s[3] / s[2]);
      if (v.length) out.push({ type: "Feature", geometry: { type: "Point", coordinates: [b[0], b[1]] }, properties: { i, m: median(v) } });
    });
    count.textContent = `${out.length.toLocaleString("sl-SI")} stavb`;
    return { type: "FeatureCollection", features: out };
  }

  function popup(b) {
    const box = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = b[3];
    const table = document.createElement("table");
    const sales = matching(b).sort((x, y) => (x[0] < y[0] ? 1 : -1));
    for (const s of sales.slice(0, 8)) {
      const tr = table.insertRow();
      for (const text of [date(s[0]), (s[1] ? "hiša " : "stan. ") + String(s[2]).replace(".", ",") + " m²", eur(s[3]), eur(s[3] / s[2]) + "/m²"])
        tr.insertCell().textContent = text;
      tr.cells[2].style.fontWeight = "600";
    }
    box.append(title, table);
    if (sales.length > 8) {
      const more = document.createElement("div");
      more.className = "more";
      more.textContent = `in še ${sales.length - 8}`;
      box.append(more);
    }
    const link = document.createElement("a");
    link.href = "/" + data.paths[b[2]];
    link.textContent = "Vse prodaje na tej ulici →";
    box.append(link);
    return box;
  }

  map.on("load", async () => {
    data = await loading;
    const latest = data.buildings.reduce((m, b) => b[4].reduce((n, s) => (s[0] > n ? s[0] : n), m), "");
    const d = new Date(latest);
    d.setFullYear(d.getFullYear() - 1);
    data.since = d.toISOString().slice(0, 10);

    map.addSource("sales", { type: "geojson", data: features() });
    const labels = map.getStyle().layers.find((l) => l.type === "symbol");   // dots go under the map's names
    map.addLayer({
      id: "sales", type: "circle", source: "sales",
      layout: { "circle-sort-key": ["get", "m"] },
      paint: {
        "circle-color": ["step", ["get", "m"], COLORS[0], ...BINS.flatMap((b, i) => [b, COLORS[i + 1]])],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 2, 11, 3, 15, 6, 18, 10],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 10, 0, 13, 1.5],
      },
    }, labels && labels.id);
    const refresh = () => map.getSource("sales").setData(features());
    kindBox.addEventListener("change", refresh);
    periodBox.addEventListener("change", refresh);

    map.on("click", "sales", (e) => {
      const b = data.buildings[e.features[0].properties.i];
      new maplibregl.Popup({ maxWidth: "340px" }).setLngLat([b[0], b[1]]).setDOMContent(popup(b)).addTo(map);
    });
    map.on("mouseenter", "sales", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "sales", () => { map.getCanvas().style.cursor = ""; });
  });
})();
