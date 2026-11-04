// Map and list of sold buildings, narrowed by place, kind, year, size and price. The filters live in the address,
// so a search can be shared and place pages can link to one (/zemljevid/?kje=koper/koper/).
// map.json: {paths, buildings: [[lon, lat, path index, address, [[day, 0 flat / 1 house, m², €], ...]], ...]}.
// search.json: [name, context, path, sales]. A place's buildings are those whose path starts with the place's path.
// A building's dot is coloured by the median €/m² of its sales that match the filters.
(() => {
  const el = document.getElementById("map");
  if (!el || !window.maplibregl) return;
  const BINS = [1500, 2500, 3500, 4500, 5500];                                 // kept in step with MAP_BINS in build.py
  const COLORS = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
  const PAGE = 100;                                                            // rows added to the list at a time
  const $ = (id) => document.getElementById(id);
  const placeBox = $("place"), placeList = $("place-list"), kindBox = $("kind"), periodBox = $("period");
  const ranges = { areaMin: $("area-min"), areaMax: $("area-max"), priceMin: $("price-min"), priceMax: $("price-max") };
  const count = $("count"), clear = $("clear"), rows = $("sale-rows"), note = $("sale-note"), more = $("sale-more");

  const num = (x) => Math.round(x).toLocaleString("sl-SI", { useGrouping: "always" });   // by default 2581, not 2.581
  const eur = (x) => num(x) + " €";
  const size = (m2) => String(m2).replace(".", ",") + " m²";
  const date = (d) => d.split("-").reverse().map(Number).join(". ");
  const median = (v) => { v.sort((a, b) => a - b); const h = v.length >> 1; return v.length % 2 ? v[h] : (v[h - 1] + v[h]) / 2; };
  const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");
  const salesWord = (n) => ({ 1: "prodaja", 2: "prodaji", 3: "prodaje", 4: "prodaje" })[n % 100] || "prodaj";
  const inPlace = (b) => !place || data.paths[b[2]].startsWith(place.path);

  const params = new URLSearchParams(location.search);
  const hadView = location.hash.length > 1;     // a shared link keeps its view; otherwise the map goes to the place
  const map = new maplibregl.Map({
    container: el, style: "https://tiles.openfreemap.org/styles/positron", hash: true,
    center: [14.85, 46.12], zoom: 7.4, minZoom: 6.5, maxBounds: [[12.4, 44.9], [17.4, 47.3]],
    customAttribution: 'Prodaje: <a href="https://www.e-prostor.gov.si/">GURS, ETN</a> (CC BY 4.0)',
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }));
  map.addControl(new maplibregl.GeolocateControl({ fitBoundsOptions: { maxZoom: 15 } }));
  const mapReady = new Promise((done) => map.once("load", done));

  let data, places, since;
  let place = null;      // the chosen entry of search.json
  let f = {};            // the filters' current values
  let found = [];        // matching sales, newest first: [sale, building]
  let shown = 0;         // how many of them are listed
  let openPopup = null;

  function readFilters() {
    const value = (box) => (box.value === "" ? null : +box.value);
    f = { kind: value(kindBox), period: periodBox.value };
    for (const key in ranges) f[key] = value(ranges[key]);
  }

  function matching(b) {
    return b[4].filter((s) => (f.kind === null || s[1] === f.kind) &&
      (f.period === "" || (f.period === "12" ? s[0] >= since : s[0].startsWith(f.period))) &&
      (f.areaMin === null || s[2] >= f.areaMin) && (f.areaMax === null || s[2] <= f.areaMax) &&
      (f.priceMin === null || s[3] >= f.priceMin) && (f.priceMax === null || s[3] <= f.priceMax));
  }

  function features() {
    const out = [];
    found = [];
    data.buildings.forEach((b, i) => {
      if (!inPlace(b)) return;
      const sales = matching(b);
      if (!sales.length) return;
      out.push({ type: "Feature", geometry: { type: "Point", coordinates: [b[0], b[1]] }, properties: { i, m: median(sales.map((s) => s[3] / s[2])) } });
      for (const s of sales) found.push([s, b]);
    });
    found.sort((x, y) => (x[0][0] < y[0][0] ? 1 : x[0][0] > y[0][0] ? -1 : 0));
    return { type: "FeatureCollection", features: out };
  }

  function tally(buildings) {
    count.replaceChildren();
    const strong = (text) => { const b = document.createElement("b"); b.textContent = text; return b; };
    const n = found.length;
    count.append(strong(`${num(n)} ${salesWord(n)}`));
    if (!n) return;
    count.append(` v ${num(buildings)} ${buildings % 100 === 1 ? "stavbi" : "stavbah"} · mediana `,
      strong(eur(median(found.map(([s]) => s[3] / s[2]))) + "/m²"), ", ",
      strong(eur(median(found.map(([s]) => s[3])))), ", ",
      strong(size(Math.round(median(found.map(([s]) => s[2]))))));
  }

  function saleRow([s, b]) {
    const tr = rows.insertRow();
    const cell = (cls, text) => { const td = tr.insertCell(); td.className = cls; td.textContent = text; return td; };
    const kind = s[1] ? "Hiša" : "Stanovanje";
    cell("d", date(s[0]));
    cell("k", kind);
    const a = document.createElement("a");
    a.href = "/" + data.paths[b[2]];
    a.textContent = b[3];
    const details = document.createElement("button");
    details.type = "button";
    details.className = "details";
    details.textContent = document.body.dataset.streetviewKey ? "Slika" : "Podrobnosti";
    details.setAttribute("aria-label", `${details.textContent}: ${b[3]}`);
    details.addEventListener("click", () => {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      showBuilding(b, Math.max(map.getZoom(), 16));
    });
    cell("a", "").append(a, details);
    cell("n s", size(s[2]));
    const price = document.createElement("b");
    price.textContent = eur(s[3]);
    cell("n p", "").append(price);
    cell("n m", eur(s[3] / s[2]) + "/m²");
    cell("meta", `${date(s[0])} · ${kind.toLowerCase()} · ${size(s[2])}`);
  }

  function listMore() {
    const end = Math.min(shown + PAGE, found.length);
    for (; shown < end; shown++) saleRow(found[shown]);
    note.textContent = !found.length ? "Nobena prodaja ne ustreza filtrom. Razširite razpon ali počistite filtre."
      : shown < found.length ? `Prikazanih je zadnjih ${num(shown)} od ${num(found.length)}.` : "";
    more.hidden = shown >= found.length;
  }

  function saveToAddress() {
    const p = new URLSearchParams();
    const put = (key, value) => { if (value !== "") p.set(key, value); };
    put("kje", place ? place.path : "");
    put("vrsta", kindBox.value);
    put("leto", periodBox.value);
    put("m2od", ranges.areaMin.value);
    put("m2do", ranges.areaMax.value);
    put("cenaod", ranges.priceMin.value);
    put("cenado", ranges.priceMax.value);
    const q = p.toString().replace(/%2F/g, "/");
    history.replaceState(history.state, "", location.pathname + (q ? "?" + q : "") + location.hash);
    clear.hidden = !q;
  }

  function refresh() {
    readFilters();
    if (openPopup) openPopup.remove();
    const geojson = features();
    const source = map.getSource("sales");
    if (source) source.setData(geojson);
    tally(geojson.features.length);
    rows.replaceChildren();
    shown = 0;
    listMore();
    saveToAddress();
  }

  function goToPlace() {
    const at = place ? data.buildings.filter(inPlace) : [];
    if (!at.length) return;
    const lons = at.map((b) => b[0]), lats = at.map((b) => b[1]);
    map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 48, maxZoom: 16 });
  }

  // ---------- place box: suggestions as you type ----------

  let options = [], active = -1;

  function suggestions() {
    const words = fold(placeBox.value).split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    return places.filter((e) => words.every((w) => e.key.includes(w)))
      .sort((a, b) => (fold(b.name).startsWith(words[0]) - fold(a.name).startsWith(words[0])) || b.n - a.n)
      .slice(0, 8);
  }

  function showOptions(list) {
    options = list;
    active = -1;
    placeList.replaceChildren();
    list.forEach((e, i) => {
      const a = document.createElement("a");
      a.href = "?kje=" + e.path;
      a.id = "place-" + i;
      a.setAttribute("role", "option");
      const name = document.createElement("span");
      name.textContent = e.name;
      const ctx = document.createElement("span");
      ctx.className = "ctx";
      ctx.textContent = `${e.ctx} · ${num(e.n)} ${salesWord(e.n)}`;
      a.append(name, ctx);
      a.addEventListener("click", (event) => { event.preventDefault(); choose(e); });
      const li = document.createElement("li");
      li.append(a);
      placeList.append(li);
    });
    placeBox.setAttribute("aria-expanded", String(list.length > 0));
    placeBox.removeAttribute("aria-activedescendant");
  }

  function highlight(i) {
    placeList.querySelector(".active")?.classList.remove("active");
    active = i;
    if (i < 0) return placeBox.removeAttribute("aria-activedescendant");
    $("place-" + i).classList.add("active");
    placeBox.setAttribute("aria-activedescendant", "place-" + i);
  }

  function choose(e) {
    place = e;
    placeBox.value = e.label;
    showOptions([]);
    refresh();
    goToPlace();
  }

  function wirePlaceBox() {
    placeBox.addEventListener("input", () => {
      showOptions(suggestions());
      if (!placeBox.value.trim() && place) { place = null; refresh(); }
    });
    placeBox.addEventListener("focus", () => placeBox.select());
    placeBox.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" && options.length) { e.preventDefault(); highlight((active + 1) % options.length); }
      else if (e.key === "ArrowUp" && options.length) { e.preventDefault(); highlight((active + options.length - 1) % options.length); }
      else if (e.key === "Escape") showOptions([]);
      else if (e.key === "Enter" && options.length) { e.preventDefault(); choose(options[Math.max(active, 0)]); }
    });
    placeList.addEventListener("pointerdown", (e) => e.preventDefault());     // keep focus, so the click lands
    placeBox.addEventListener("blur", () => {      // typed a name and moved on: take the best match
      const text = placeBox.value.trim();
      showOptions([]);
      if (!text || (place && text === place.label)) return;
      const best = suggestions()[0];
      if (best) choose(best);
      else placeBox.value = place ? place.label : "";
    });
  }

  // ---------- list and map ----------

  // The details are tall, so the building moves near the map's bottom edge (above the attribution) with them
  // above it, scrolling if need be.
  function showBuilding(b, zoom = map.getZoom()) {
    if (openPopup) openPopup.remove();
    map.easeTo({ center: [b[0], b[1]], zoom, offset: [0, el.clientHeight / 2 - 70] });
    openPopup = new maplibregl.Popup({ maxWidth: "340px", anchor: "bottom", focusAfterOpen: false })
      .setLngLat([b[0], b[1]]).setDOMContent(popup(b)).addTo(map);
    openPopup.getElement().querySelector(".maplibregl-popup-content").style.maxHeight = `${el.clientHeight - 100}px`;
  }

  function popup(b) {
    const box = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = b[3];
    const table = document.createElement("table");
    const sales = matching(b).sort((x, y) => (x[0] < y[0] ? 1 : -1));
    for (const s of sales.slice(0, 8)) {
      const tr = table.insertRow();
      for (const text of [date(s[0]), (s[1] ? "hiša " : "stan. ") + size(s[2]), eur(s[3]), eur(s[3] / s[2]) + "/m²"])
        tr.insertCell().textContent = text;
      tr.cells[2].style.fontWeight = "600";
    }
    box.append(title, window.buildingPhoto(`${b[1]},${b[0]}`, b[3]), table);
    if (sales.length > 8) {
      const extra = document.createElement("div");
      extra.className = "more";
      extra.textContent = `in še ${sales.length - 8}`;
      box.append(extra);
    }
    const link = document.createElement("a");
    link.href = "/" + data.paths[b[2]];
    link.textContent = "Vse prodaje na tej ulici →";
    box.append(link);
    return box;
  }

  function restoreFilters() {
    const set = (box, key) => { box.value = params.get(key) ?? ""; if (box.selectedIndex < 0) box.value = ""; };
    set(kindBox, "vrsta");
    set(periodBox, "leto");
    ranges.areaMin.value = params.get("m2od") ?? "";
    ranges.areaMax.value = params.get("m2do") ?? "";
    ranges.priceMin.value = params.get("cenaod") ?? "";
    ranges.priceMax.value = params.get("cenado") ?? "";
    place = places.find((e) => e.path === params.get("kje")) || null;
    if (place) placeBox.value = place.label;
  }

  function wireFilters() {
    wirePlaceBox();
    kindBox.addEventListener("change", refresh);
    periodBox.addEventListener("change", refresh);
    let timer;
    for (const box of Object.values(ranges))
      box.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(refresh, 200); });
    $("filters").addEventListener("submit", (e) => e.preventDefault());
    more.addEventListener("click", listMore);
    clear.addEventListener("click", () => {
      place = null;
      placeBox.value = "";
      kindBox.value = periodBox.value = "";
      for (const box of Object.values(ranges)) box.value = "";
      refresh();
    });
  }

  (async () => {
    const [mapData, placeRows] = await Promise.all([fetch("/map.json").then((r) => r.json()), fetch("/search.json").then((r) => r.json())]);
    data = mapData;
    places = placeRows.map(([name, ctx, path, n]) => ({
      name, ctx, path, n, key: fold(name + " " + ctx),
      label: ctx === "občina" ? `Občina ${name}` : `${name} (${ctx})`,
    }));
    const latest = data.buildings.reduce((m, b) => b[4].reduce((n, s) => (s[0] > n ? s[0] : n), m), "");
    const d = new Date(latest);
    d.setFullYear(d.getFullYear() - 1);
    since = d.toISOString().slice(0, 10);

    restoreFilters();
    wireFilters();
    refresh();                 // the list works even if the map's tiles don't load

    await mapReady;
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
    if (place && !hadView && !openPopup) goToPlace();     // not if a building was opened while the map loaded

    map.on("click", "sales", (e) => {
      showBuilding(data.buildings[e.features[0].properties.i]);
    });
    map.on("mouseenter", "sales", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "sales", () => { map.getCanvas().style.cursor = ""; });
  })();
})();
