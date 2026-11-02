// Search over streets, towns and municipalities (search.json: [name, context, path, sales]).
// On the home page results show as you type; the header box elsewhere opens /?q=...
(() => {
  const box = document.getElementById("q");
  const list = document.getElementById("results");
  if (!box || !list) return;
  const fold = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d");
  let entries = null;

  async function load() {
    if (!entries) {
      const rows = await (await fetch("/search.json")).json();
      entries = rows.map((r) => ({ name: r[0], ctx: r[1], path: r[2], n: r[3], key: fold(r[0] + " " + r[1]) }));
    }
    return entries;
  }

  async function show() {
    const words = fold(box.value).split(/\s+/).filter(Boolean);
    list.replaceChildren();
    if (!words.length) return;
    const all = await load();
    const found = all.filter((e) => words.every((w) => e.key.includes(w)))
      .sort((a, b) => (fold(b.name).startsWith(words[0]) - fold(a.name).startsWith(words[0])) || b.n - a.n)
      .slice(0, 20);
    for (const e of found) {
      const a = document.createElement("a");
      a.href = "/" + e.path;
      const name = document.createElement("span");
      name.textContent = e.name;
      const ctx = document.createElement("span");
      ctx.className = "ctx";
      ctx.textContent = `${e.ctx} · ${e.n} prodaj`;
      a.append(name, ctx);
      const li = document.createElement("li");
      li.append(a);
      list.append(li);
    }
    if (!found.length) list.innerHTML = '<li><a href="#">Ni zadetkov</a></li>';
  }

  box.addEventListener("input", show);
  const q = new URLSearchParams(location.search).get("q");
  if (q) { box.value = q; show(); }
})();
