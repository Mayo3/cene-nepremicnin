"""Static website of what flats and houses actually sold for in Slovenia, by municipality,
town and street.

  python build.py [OUT] [YEARS]     OUT defaults to public/, YEARS (of sales) to 6

Source: GURS, Evidenca trga nepremičnin (public geodetic data, CC BY 4.0, updated weekly). Keeps
open-market sales of exactly one whole flat or house (a garage, parking space or storage room may
be included), with a price and a size. Flat numbers are left out so a sale isn't tied to a home.
Set SITE_URL for canonical links and the sitemap. Standard library only.
"""
import csv
import html
import io
import json
import os
import re
import shutil
import statistics
import sys
import time
import unicodedata
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "data"
SITE_URL = os.environ.get("SITE_URL", "https://cenenepremicnin.si").rstrip("/")
SITE_NAME = "Prodajne cene nepremičnin"
API = "https://ipi.eprostor.gov.si/jgp-service-api/display-views/groups/127/composite-products/321"
DWELLINGS = {"1": "hisa", "2": "stanovanje"}      # Vrsta dela stavbe: house, flat
EXTRAS = {"3", "4", "14"}                         # parking space, garage, storage/technical rooms
MARKET = {"1", "2", "5"}                          # Tržnost posla: market sales (5: still being checked)
INDEX_MIN = 3        # streets with fewer sales get a page, but search engines are asked to skip it
TABLE_MAX = 150      # sales listed on a municipality or town page
RECENT_DAYS = 365


# ---------- data ----------

def download(year):
    """The year's sales zip, cached in data/ for six days (GURS updates weekly)."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"ETN_{year}.zip"
    if not path.exists() or time.time() - path.stat().st_mtime > 6 * 86400:
        with urllib.request.urlopen(f"{API}/file?filterParam=DRZAVA&filterValue=1&filterYear={year}", timeout=60) as r:
            link = json.load(r)["url"]            # a short-lived link to the zip
        with urllib.request.urlopen(link, timeout=300) as r:
            path.write_bytes(r.read())
    return zipfile.ZipFile(path)


def table(zf, part):
    name = next(n for n in zf.namelist() if f"_KPP_{part}_" in n)
    return csv.DictReader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig"))


def number(text):
    try:
        return float(text.replace(",", ".")) if text else None
    except ValueError:
        return None


SMALL = {"pri", "ob", "na", "v", "pod", "nad", "in", "za", "pred", "od", "do", "s", "z",
         "ulica", "cesta", "trg", "pot", "nabrežje", "steza", "drevored", "naselje", "breg", "vas", "ul.", "c."}
ROMAN = re.compile(r"^[IVX]+\.?$")


def name(text):
    """'CESTA CENETA ŠTUPARJA' -> 'Cesta Ceneta Štuparja', 'CELOVŠKA CESTA' -> 'Celovška cesta'."""
    words = []
    for i, w in enumerate((text or "").split()):
        low = w.lower()
        words.append(w if ROMAN.match(w) else low if i and low in SMALL
                     else "-".join(p.capitalize() for p in low.split("-")))
    return " ".join(words)


def slug(text):
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    return re.sub(r"[^a-z0-9]+", "-", text.encode("ascii", "ignore").decode().lower()).strip("-") or "x"


def sales(zf):
    deals = {r["ID_POSLA"]: r for r in table(zf, "POSLI")
             if r["TRZNOST_POSLA"] in MARKET and r["VRSTA_KUPOPRODAJNEGA_POSLA"] == "1" and r["VRSTA_AKTA"] == "1"}
    parts = defaultdict(list)
    for r in table(zf, "DELISTAVB"):
        if r["ID_POSLA"] in deals:
            parts[r["ID_POSLA"]].append(r)
    for deal_id, deal_parts in parts.items():
        homes = [p for p in deal_parts if p["VRSTA_DELA_STAVBE"] in DWELLINGS]
        others = [p for p in deal_parts if p["VRSTA_DELA_STAVBE"] not in DWELLINGS]
        if len(homes) != 1 or any(p["VRSTA_DELA_STAVBE"] not in EXTRAS for p in others):
            continue
        home, deal = homes[0], deals[deal_id]
        if home["PRODANI_DELEZ_DELA_STAVBE"] not in ("1/1", "") or not home["OBCINA"] or not home["NASELJE"]:
            continue
        price = number(deal["POGODBENA_CENA_ODSKODNINA"])
        area = number(home["UPORABNA_POVRSINA"]) or number(home["PRODANA_POVRSINA"]) or number(home["POVRSINA_DELA_STAVBE"])
        if not price or not area or price < 10000 or area < 12 or not 300 <= price / area <= 20000:
            continue
        day, month, year = (deal["DATUM_SKLENITVE_POGODBE"] or deal["DATUM_UVELJAVITVE"]).split(".")
        built = number(home["LETO_IZGRADNJE_DELA_STAVBE"])
        yield {
            "municipality": name(home["OBCINA"]), "town": name(home["NASELJE"]), "street": name(home["ULICA"]) or None,
            "number": (home["HISNA_STEVILKA"] + home["DODATEK_HS"]).strip(),
            "kind": DWELLINGS[home["VRSTA_DELA_STAVBE"]], "day": f"{year}-{month}-{day}",
            "price": round(price), "area": round(area, 1), "built": int(built) if built else None,
            "new": home["NOVOGRADNJA"] == "1", "garage": bool(others),
        }


def load(years):
    rows, seen = [], set()
    first = date.today().year - years + 1
    for year in range(first, date.today().year + 1):
        found = 0
        for s in sales(download(year)):
            key = (s["municipality"], s["town"], s["street"], s["number"], s["day"], s["price"], s["area"])
            # A year's file also holds older contracts registered late; a deal changed later can
            # appear in two years' files.
            if s["day"] >= f"{first}-01-01" and key not in seen:
                seen.add(key)
                rows.append(s)
                found += 1
        print(f"{year}: {found} sales")
    rows.sort(key=lambda s: s["day"], reverse=True)
    return rows


# ---------- numbers ----------

def num(x):
    return f"{round(x):,}".replace(",", ".")


def eur(x):
    return num(x) + " €"


def per_m2(s):
    return s["price"] / s["area"]


def day(iso):
    y, m, d = iso.split("-")
    return f"{int(d)}. {int(m)}. {y}"


def summary(rows, since):
    """Per kind: number sold, median €/m², median price, median size - over all rows and recent ones."""
    out = {}
    for kind in ("stanovanje", "hisa"):
        all_ = [s for s in rows if s["kind"] == kind]
        recent = [s for s in all_ if s["day"] >= since]
        out[kind] = {
            "n": len(all_), "n_recent": len(recent),
            "m2": statistics.median(map(per_m2, all_)) if all_ else None,
            "m2_recent": statistics.median(map(per_m2, recent)) if len(recent) >= 3 else None,
            "price": statistics.median(s["price"] for s in all_) if all_ else None,
            "area": statistics.median(s["area"] for s in all_) if all_ else None,
        }
    return out


# ---------- pages ----------

def esc(x):
    return html.escape(str(x))


def page(path, title, description, body, crumbs=(), index=True):
    url = f"{SITE_URL}/{path}"
    nav = "".join(f'<a href="/{esc(p)}">{esc(t)}</a> › ' for t, p in crumbs)
    return f"""<!doctype html>
<html lang="sl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(url)}">{'' if index else chr(10) + '<meta name="robots" content="noindex,follow">'}
<link rel="stylesheet" href="/style.css">
</head><body>
<header><a class="brand" href="/">{SITE_NAME}</a>
<form class="search" action="/" role="search"><input name="q" type="search" placeholder="Ulica, kraj ali občina" aria-label="Iskanje"></form></header>
<main>
{f'<nav class="crumbs">{nav}</nav>' if nav else ''}
{body}
</main>
<footer>Vir podatkov: Geodetska uprava RS, Evidenca trga nepremičnin (javni geodetski podatki, CC BY 4.0),
osveženo {day(date.today().isoformat())}.
Prikazane so tržne prodaje celih stanovanj in hiš; cene hiš vključujejo zemljišče. Podatki so informativni.</footer>
<script src="/search.js" defer></script>
</body></html>"""


def cards(st):
    def card(label, value, note=""):
        return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div><div class="note">{note}</div></div>'
    out = []
    f, h = st["stanovanje"], st["hisa"]
    if f["n"]:
        out.append(card("Stanovanja, mediana €/m²", eur(f["m2_recent"] or f["m2"]),
                        f"zadnjih 12 mesecev ({f['n_recent']} prodaj)" if f["m2_recent"] else f"vse prodaje ({f['n']})"))
        out.append(card("Tipično stanovanje", eur(f["price"]), f"{f['area']:.0f} m², mediana"))
    if h["n"]:
        out.append(card("Hiše, mediana €/m²", eur(h["m2_recent"] or h["m2"]),
                        f"zadnjih 12 mesecev ({h['n_recent']} prodaj)" if h["m2_recent"] else f"vse prodaje ({h['n']})"))
        out.append(card("Tipična hiša", eur(h["price"]), f"{h['area']:.0f} m², mediana"))
    return f'<div class="cards">{"".join(out)}</div>'


def by_year(rows):
    years = defaultdict(lambda: {"stanovanje": [], "hisa": []})
    for s in rows:
        years[s["day"][:4]][s["kind"]].append(per_m2(s))
    if len(years) < 2:
        return ""
    def cell(v):
        return f"<td>{len(v)}</td><td>{eur(statistics.median(v)) if v else '–'}</td>"
    body = "".join(f"<tr><th>{y}</th>{cell(k['stanovanje'])}{cell(k['hisa'])}</tr>" for y, k in sorted(years.items(), reverse=True))
    return f"""<h2>Po letih</h2><div class="scroll"><table>
<thead><tr><th>Leto</th><th>Stanovanj</th><th>€/m²</th><th>Hiš</th><th>€/m²</th></tr></thead><tbody>{body}</tbody></table></div>"""


def places(title, items):
    """items: (name, link, rows)"""
    if not items:
        return ""
    def med(rows, kind):
        v = [per_m2(s) for s in rows if s["kind"] == kind]
        return eur(statistics.median(v)) if v else "–"
    body = "".join(
        f'<tr><th><a href="/{esc(link)}">{esc(n)}</a></th><td>{sum(s["kind"] == "stanovanje" for s in rows)}</td>'
        f'<td>{med(rows, "stanovanje")}</td><td>{sum(s["kind"] == "hisa" for s in rows)}</td><td>{med(rows, "hisa")}</td>'
        f'<td>{day(rows[0]["day"])}</td></tr>'
        for n, link, rows in sorted(items, key=lambda i: -len(i[2])))
    return f"""<h2>{title}</h2><div class="scroll"><table class="places">
<thead><tr><th>Ime</th><th>Stanovanj</th><th>€/m²</th><th>Hiš</th><th>€/m²</th><th>Zadnja prodaja</th></tr></thead><tbody>{body}</tbody></table></div>"""


def sale_table(rows, show_town, limit=None):
    shown = rows[:limit] if limit else rows
    def where(s):
        street = s["street"] or (s["town"] if not show_town else "")
        addr = f"{street} {s['number']}".strip()
        return ", ".join(x for x in (addr, s["town"] if show_town and s["street"] else "") if x) or s["town"]
    body = "".join(
        f'<tr><td>{day(s["day"])}</td><td>{"Stanovanje" if s["kind"] == "stanovanje" else "Hiša"}{" · novogradnja" if s["new"] else ""}</td>'
        f'<td>{esc(where(s))}</td><td class="n">{f"{s['area']:g}".replace(".", ",")} m²</td><td class="n">{s["built"] or "–"}</td>'
        f'<td class="n"><b>{eur(s["price"])}</b></td><td class="n">{eur(per_m2(s))}</td></tr>'
        for s in shown)
    more = f'<p class="note">Prikazanih je zadnjih {len(shown)} od {len(rows)} prodaj; vse najdete na straneh posameznih ulic in krajev.</p>' if len(shown) < len(rows) else ""
    return f"""<h2>Prodaje</h2><div class="scroll"><table class="sales">
<thead><tr><th>Datum</th><th>Vrsta</th><th>Naslov</th><th>Velikost</th><th>Leto gradnje</th><th>Cena</th><th>€/m²</th></tr></thead>
<tbody>{body}</tbody></table></div>{more}"""


def intro(where, st, rows):
    f = st["stanovanje"]
    first, last = day(rows[-1]["day"]), day(rows[0]["day"])
    text = f"Od {first} do {last} je bilo {where} prodanih {len(rows)} stanovanj in hiš."
    if f["n"]:
        text += f" Mediana cene stanovanj je {eur(f['m2_recent'] or f['m2'])} na m²."
    return f'<p class="lead">{esc(text)}</p>'


def write(out, path, content):
    target = out / path / "index.html" if path else out / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def build(out, rows):
    out.mkdir(exist_ok=True)
    for old in out.iterdir():              # empty it rather than delete it: a preview server may be in it
        shutil.rmtree(old) if old.is_dir() else old.unlink()
    shutil.copytree(ROOT / "static", out, dirs_exist_ok=True)
    latest = date.fromisoformat(rows[0]["day"])
    since = date.fromordinal(latest.toordinal() - RECENT_DAYS).isoformat()

    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))   # municipality > town > street
    for s in rows:
        tree[s["municipality"]][s["town"]][s["street"]].append(s)

    search, sitemap, munis = [], [], []
    for m, towns in tree.items():
        m_path = f"{slug(m)}/"
        m_rows = sorted((s for t in towns.values() for st in t.values() for s in st), key=lambda s: s["day"], reverse=True)
        munis.append((m, m_path, m_rows))
        town_items = []
        for t, streets in towns.items():
            t_path = f"{m_path}{slug(t)}/"
            t_rows = sorted((s for st in streets.values() for s in st), key=lambda s: s["day"], reverse=True)
            town_items.append((t, t_path, t_rows))
            street_items = []
            for st_name, st_rows in streets.items():
                if not st_name:
                    continue
                st_path = f"{t_path}{slug(st_name)}/"
                street_items.append((st_name, st_path, st_rows))
                indexed = len(st_rows) >= INDEX_MIN
                where = f"{st_name}, {t}"
                stats = summary(st_rows, since)
                write(out, st_path, page(
                    st_path, f"{where}: prodajne cene stanovanj in hiš",
                    f"Za koliko so se dejansko prodala stanovanja in hiše na naslovu {where}: {len(st_rows)} prodaj z datumi, velikostmi in cenami na m².",
                    f"<h1>{esc(st_name)}<small>{esc(t)}</small></h1>{intro('na naslovu ' + where, stats, st_rows)}{cards(stats)}"
                    f"{sale_table(st_rows, False)}{by_year(st_rows)}",
                    crumbs=((m, m_path), (t, t_path)), index=indexed))
                search.append([st_name, t, st_path, len(st_rows)])
                if indexed:
                    sitemap.append(st_path)
            stats = summary(t_rows, since)
            no_street = streets.get(None, [])
            listing = sale_table(t_rows, False, None if len(t_rows) <= TABLE_MAX else TABLE_MAX)
            write(out, t_path, page(
                t_path, f"{t}: prodajne cene stanovanj in hiš" + (f" ({m})" if m != t else ""),
                f"Dejanske prodajne cene nepremičnin v kraju {t}: {len(t_rows)} prodaj stanovanj in hiš, cene na m² po ulicah in letih.",
                f"<h1>{esc(t)}<small>občina {esc(m)}</small></h1>{intro('v kraju ' + t, stats, t_rows)}{cards(stats)}"
                f"{places('Ulice', street_items)}{by_year(t_rows)}{listing}",
                crumbs=((m, m_path),), index=len(t_rows) >= INDEX_MIN))
            search.append([t, f"občina {m}" if m != t else "kraj", t_path, len(t_rows)])
            if len(t_rows) >= INDEX_MIN:
                sitemap.append(t_path)
        stats = summary(m_rows, since)
        write(out, m_path, page(
            m_path, f"Občina {m}: prodajne cene stanovanj in hiš",
            f"Za koliko se prodajajo stanovanja in hiše v občini {m}: {len(m_rows)} dejanskih prodaj, cene na m² po krajih in letih.",
            f"<h1>Občina {esc(m)}</h1>{intro('v občini ' + m, stats, m_rows)}{cards(stats)}"
            f"{places('Kraji', town_items)}{by_year(m_rows)}{sale_table(m_rows, True, TABLE_MAX)}"))
        search.append([m, "občina", m_path, len(m_rows)])
        sitemap.append(m_path)

    stats = summary(rows, since)
    write(out, "", page(
        "", f"{SITE_NAME} v Sloveniji – za koliko so se stanovanja res prodala",
        "Dejanske prodajne cene stanovanj in hiš v Sloveniji po ulicah, krajih in občinah, iz uradne evidence trga nepremičnin. Brezplačno.",
        f"""<h1>Za koliko so se stanovanja in hiše res prodala?</h1>
<p class="lead">Oglasi kažejo, koliko prodajalci želijo. Tu so cene, za katere so se nepremičnine dejansko prodale:
{num(len(rows))} prodaj od {day(rows[-1]['day'])} do {day(rows[0]['day'])}, po ulicah, krajih in občinah.</p>"""
        + f"""<form class="big-search" action="/" role="search"><input id="q" name="q" type="search" autocomplete="off"
placeholder="Vpišite ulico, kraj ali občino, npr. Celovška cesta" aria-label="Iskanje"></form>
<ul id="results" class="results"></ul>
{cards(stats)}{by_year(rows)}{places('Občine', munis)}"""))
    sitemap.insert(0, "")

    (out / "search.json").write_text(json.dumps(search, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"<url><loc>{esc(SITE_URL)}/{esc(p)}</loc></url>\n" for p in sitemap) + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
    files = sum(1 for _ in out.rglob("*") if _.is_file())
    print(f"{len(rows)} sales -> {len(search)} pages ({len(sitemap)} in the sitemap), {files} files in {out}")


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "public"
    years = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    build(out, load(years))


if __name__ == "__main__":
    main()
