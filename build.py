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
import functools
import hashlib
import json
import math
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
SITE_NAME = "cenenepremicnin.si"
API = "https://ipi.eprostor.gov.si/jgp-service-api/display-views/groups/127/composite-products/321"
DWELLINGS = {"1": "hisa", "2": "stanovanje"}      # Vrsta dela stavbe: house, flat
EXTRAS = {"3", "4", "14"}                         # parking space, garage, storage/technical rooms
MARKET = {"1", "2", "5"}                          # Tržnost posla: market sales (5: still being checked)
CHEAP = {"stanovanje": 0.4, "hisa": 0.3}          # below this share of the municipality's median €/m²: left out
                                                  # (houses vary more: old ruins sell for little)
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


def d96_to_wgs84(e, n):
    """Slovenian D96/TM metres -> (lat, lon) in degrees (inverse transverse Mercator on GRS80)."""
    a, f = 6378137.0, 1 / 298.257222101
    k0, lon0, fe, fn = 0.9999, math.radians(15), 500000.0, -5000000.0
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    mu = (n - fn) / k0 / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu) + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
         + 151 * e1**3 / 96 * math.sin(6 * mu) + 1097 * e1**4 / 512 * math.sin(8 * mu))
    c, t = ep2 * math.cos(p)**2, math.tan(p)**2
    nu = a / math.sqrt(1 - e2 * math.sin(p)**2)
    rho = a * (1 - e2) / (1 - e2 * math.sin(p)**2)**1.5
    d = (e - fe) / (nu * k0)
    lat = p - nu * math.tan(p) / rho * (d**2 / 2 - (5 + 3 * t + 10 * c - 4 * c**2 - 9 * ep2) * d**4 / 24
                                        + (61 + 90 * t + 298 * c + 45 * t**2 - 252 * ep2 - 3 * c**2) * d**6 / 720)
    lon = lon0 + (d - (1 + 2 * t + c) * d**3 / 6
                  + (5 - 2 * c + 28 * t - 3 * c**2 + 8 * ep2 + 24 * t**2) * d**5 / 120) / math.cos(p)
    return round(math.degrees(lat), 5), round(math.degrees(lon), 5)


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
        e, n = number(home["E_CENTROID"]), number(home["N_CENTROID"])   # the building's centre, for the map
        yield {
            "at": d96_to_wgs84(e, n) if e and n else None,
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
    rows = [s for s in rows if not cheap(s, rows)]
    rows.sort(key=lambda s: s["day"], reverse=True)
    return rows


_local = {}


def cheap(s, rows):
    """A sale far below the municipality's usual €/m² for its kind: most likely to family or a friend
    though not declared as such (most sales are still 'being checked' by GURS), not a market price."""
    if not _local:
        groups = defaultdict(list)
        for r in rows:
            groups[r["municipality"], r["kind"]].append(per_m2(r))
        _local.update({k: statistics.median(v) for k, v in groups.items() if len(v) >= 10})
    usual = _local.get((s["municipality"], s["kind"]))
    return usual is not None and per_m2(s) < CHEAP[s["kind"]] * usual


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


def sold(n):
    """'1 prodaja', '2 prodaji', '3 prodaje', '5 prodaj'."""
    word = {1: "prodaja", 2: "prodaji", 3: "prodaje", 4: "prodaje"}.get(n % 100, "prodaj")
    return f"{num(n)} {word}"


NAV = (("Zemljevid", "zemljevid/"), ("Lestvice", "lestvice/"), ("O podatkih", "o-podatkih/"))
BRAND = '<a class="brand" href="/">cenenepremicnin<span>.si</span></a>'


@functools.cache
def asset(name):
    """/name?v=<content hash>: browsers keep static files for hours, so a changed file needs a new address."""
    return f"/{name}?v={hashlib.sha256((ROOT / 'static' / name).read_bytes()).hexdigest()[:8]}"


def page(path, title, description, body, crumbs=(), index=True, head="", scripts=""):
    url = f"{SITE_URL}/{path}"
    trail = "".join(f'<a href="/{esc(p)}">{esc(t)}</a> › ' for t, p in crumbs)
    links = "".join(f'<a href="/{p}"{" aria-current=page" if p == path else ""}>{t}</a>' for t, p in NAV)
    return f"""<!doctype html>
<html lang="sl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(url)}">{'' if index else chr(10) + '<meta name="robots" content="noindex,follow">'}
<link rel="stylesheet" href="{asset('style.css')}">{head}
</head><body>
<header><div class="bar">{BRAND}<nav class="menu">{links}</nav>
<form class="search" action="/" role="search"><input name="q" type="search" placeholder="Ulica, kraj ali občina" aria-label="Iskanje"></form></div></header>
<main>
{f'<nav class="crumbs">{trail}</nav>' if trail else ''}
{body}
</main>
<footer><div class="cols">
<div>{BRAND}<p>Prodajne cene stanovanj in hiš v Sloveniji po ulicah, krajih in občinah.</p></div>
<nav>{links}<a href="/">Iskanje</a></nav></div>
<p>Vir podatkov: Geodetska uprava RS, Evidenca trga nepremičnin (javni geodetski podatki, CC BY 4.0),
osveženo {day(date.today().isoformat())}. Cene hiš vključujejo zemljišče. Podatki so informativni.</p></footer>
<script src="{asset('search.js')}" defer></script>{scripts}
</body></html>"""


_memo = {}


def memo(fn):
    """Per-row-list results, so a town's figures aren't recomputed for each of its streets."""
    def wrapper(rows, *args):
        key = (fn.__name__, id(rows), args)
        if key not in _memo:
            _memo[key] = fn(rows, *args)
        return _memo[key]
    return wrapper


@memo
def m2_of(rows, kind):
    return [per_m2(s) for s in rows if s["kind"] == kind]


def main_kind(rows):
    return "stanovanje" if 2 * sum(s["kind"] == "stanovanje" for s in rows) >= len(rows) else "hisa"


def figures(st):
    def fig(label, value, note):
        return f"<div><dt>{label}</dt><dd>{value}</dd><p>{note}</p></div>"
    out = []
    for word, typical, s in (("Stanovanja", "Tipično stanovanje", st["stanovanje"]), ("Hiše", "Tipična hiša", st["hisa"])):
        if s["n"]:
            recent = s["m2_recent"] is not None
            out.append(fig(f"{word}, cena na m²", eur(s["m2_recent"] if recent else s["m2"]),
                           f"mediana zadnjih 12 mesecev, {sold(s['n_recent'])}" if recent else f"mediana vseh let, {sold(s['n'])}"))
            out.append(fig(typical, eur(s["price"]), f"mediana, {s['area']:.0f} m²"))
    return f'<dl class="figures">{"".join(out)}</dl>'


def comparison(here, rows, there, parent, since):
    """One sentence comparing the place with the bigger one around it, over the same period as the figures."""
    for kind, word in (("stanovanje", "stanovanj"), ("hisa", "hiš")):
        for start, when in ((since, " v zadnjih 12 mesecih"), ("", "")):
            a = [per_m2(s) for s in rows if s["kind"] == kind and s["day"] >= start]
            b = [per_m2(s) for s in parent if s["kind"] == kind and s["day"] >= start]
            if len(a) >= 3 and len(b) >= 3:
                ma, mb = statistics.median(a), statistics.median(b)
                pct = round((ma / mb - 1) * 100)
                how = "približno enaka kot" if abs(pct) < 3 else f"za {abs(pct)} % {'višja' if pct > 0 else 'nižja'} kot"
                return (f'<p class="compare">Mediana cene {word} {esc(here)} je bila{when} {eur(ma)} na m², '
                        f'{how} {esc(there)} ({eur(mb)} na m²).</p>')
    return ""


def map_link(rows, zoom):
    at = [s["at"] for s in rows if s["at"]]
    if not at:
        return ""
    lat, lon = statistics.median(a[0] for a in at), statistics.median(a[1] for a in at)
    return f'<p class="maplink"><a href="/zemljevid/#{zoom}/{lat:.4f}/{lon:.4f}">Prodaje na zemljevidu →</a></p>'


@memo
def periods(rows, kind, quarterly):
    """(t, median €/m², sales) per quarter or year; t is the period's midpoint in years."""
    groups = defaultdict(list)
    for s in rows:
        if s["kind"] == kind:
            y, m = int(s["day"][:4]), int(s["day"][5:7])
            groups[y + ((m - 1) // 3 + 0.5) / 4 if quarterly else y + 0.5].append(per_m2(s))
    need = 5 if quarterly else 3
    return sorted((t, statistics.median(v), len(v)) for t, v in groups.items() if len(v) >= need)


def period_name(t, quarterly):
    return f"{int((t % 1) * 4) + 1}. četrtletje {int(t)}" if quarterly else str(int(t))


def trend(lines):
    """Line chart of the median €/m². lines: (label, rows, kind); the first is the place itself, the others
    are drawn as references. By quarter when the place has enough sales, otherwise by year."""
    label0, rows0, kind0 = lines[0]
    quarterly = len(m2_of(rows0, kind0)) >= 200
    series = [(label, periods(rows, kind, quarterly)) for label, rows, kind in lines]
    series = [(label, p) for label, p in series if len(p) >= 2]
    if not series or series[0][0] != label0:
        return ""
    W, H, L, R, T, B = 720, 270, 64, 128, 12, 32
    ts = [t for _, p in series for t, _, _ in p]
    vs = [v for _, p in series for _, v, _ in p]
    t0, t1 = math.floor(min(ts)), math.ceil(max(ts))
    step = next(s for s in (100, 200, 250, 500, 1000, 2000, 5000) if (max(vs) - min(vs)) / s <= 4)
    lo, hi = math.floor(min(vs) / step) * step, math.ceil(max(vs) / step) * step
    hi += step if hi == lo else 0
    x = lambda t: L + (t - t0) / (t1 - t0) * (W - L - R)
    y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    svg = []
    for v in range(lo, hi + 1, step):
        svg.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                   f'<text class="tick" x="{L - 8}" y="{y(v):.1f}" dominant-baseline="middle" text-anchor="end">{num(v)}</text>')
    for yr in range(t0, t1):
        svg.append(f'<text class="tick" x="{x(yr + 0.5):.1f}" y="{H - 8}" text-anchor="middle">{yr}</text>')
    ends = []
    for i, (label, p) in enumerate(series):
        cls = "s1" if i == 0 else "ref"
        d = "M" + " L".join(f"{x(t):.1f},{y(v):.1f}" for t, v, _ in p)
        svg.append(f'<path class="line {cls}" d="{d}"/>')
        for t, v, n in p:
            if not quarterly:
                svg.append(f'<circle class="dot {cls}" cx="{x(t):.1f}" cy="{y(v):.1f}" r="4"/>')
            svg.append(f'<circle class="hit" cx="{x(t):.1f}" cy="{y(v):.1f}" r="9"><title>{esc(label)}, '
                       f'{period_name(t, quarterly)}: {eur(v)} na m² ({sold(n)})</title></circle>')
        ends.append([y(p[-1][1]), x(p[-1][0]), label, cls])
    ends.sort()
    for a, b in zip(ends, ends[1:]):      # keep end labels from overlapping
        b[0] = max(b[0], a[0] + 18)
    for ey, ex, label, cls in ends:
        short = label if len(label) <= 11 else label[:10].rstrip() + "…"
        svg.append(f'<text class="end {cls}" x="{ex + 10:.1f}" y="{ey:.1f}" dominant-baseline="middle">{esc(short)}</text>')
    word = ("stanovanj " if kind0 == "stanovanje" else "hiš ") if len({k for _, _, k in lines}) == 1 else ""
    legend = "".join(f'<span><i class="{"s1" if i == 0 else "ref"}"></i>{esc(label)}</span>' for i, (label, _) in enumerate(series))
    return f"""<figure class="chart"><figcaption><b>Mediana cene {word}na m²</b><span>po {'četrtletjih' if quarterly else 'letih'}</span>
<span class="legend">{legend}</span></figcaption>
<svg viewBox="0 0 {W} {H}" role="img" aria-label="Mediana cene {word}na m² po {'četrtletjih' if quarterly else 'letih'}">{''.join(svg)}</svg></figure>"""


def by_year(rows):
    years = defaultdict(lambda: {"stanovanje": [], "hisa": []})
    for s in rows:
        years[s["day"][:4]][s["kind"]].append(per_m2(s))
    if len(years) < 2:
        return ""
    def cell(v):
        return f'<td class="n">{len(v)}</td><td class="n">{eur(statistics.median(v)) if v else "–"}</td>'
    body = "".join(f"<tr><th>{y}</th>{cell(k['stanovanje'])}{cell(k['hisa'])}</tr>" for y, k in sorted(years.items(), reverse=True))
    return f"""<h2>Po letih</h2><div class="scroll"><table>
<thead><tr><th>Leto</th><th class="n">Stanovanj</th><th class="n">€/m²</th><th class="n">Hiš</th><th class="n">€/m²</th></tr></thead><tbody>{body}</tbody></table></div>"""


def places(title, items):
    """items: (name, link, rows)"""
    if not items:
        return ""
    def med(rows, kind):
        v = m2_of(rows, kind)
        return eur(statistics.median(v)) if v else "–"
    body = "".join(
        f'<tr><th><a href="/{esc(link)}">{esc(n)}</a></th><td class="n">{sum(s["kind"] == "stanovanje" for s in rows)}</td>'
        f'<td class="n">{med(rows, "stanovanje")}</td><td class="n">{sum(s["kind"] == "hisa" for s in rows)}</td>'
        f'<td class="n">{med(rows, "hisa")}</td><td class="n">{day(rows[0]["day"])}</td></tr>'
        for n, link, rows in sorted(items, key=lambda i: -len(i[2])))
    return f"""<h2>{title}</h2><div class="scroll"><table class="places">
<thead><tr><th>Ime</th><th class="n">Stanovanj</th><th class="n">€/m²</th><th class="n">Hiš</th><th class="n">€/m²</th><th class="n">Zadnja prodaja</th></tr></thead><tbody>{body}</tbody></table></div>"""


def sale_table(rows, show_town, limit=None, title="Prodaje", note=True):
    shown = rows[:limit] if limit else rows
    def where(s):
        street = s["street"] or (s["town"] if not show_town else "")
        addr = f"{street} {s['number']}".strip()
        return ", ".join(x for x in (addr, s["town"] if show_town and s["street"] else "") if x) or s["town"]
    def row(s):
        kind = ("Stanovanje" if s["kind"] == "stanovanje" else "Hiša") + (" · novogradnja" if s["new"] else "")
        size = f"{s['area']:g}".replace(".", ",") + " m²"
        meta = " · ".join(x for x in (day(s["day"]), kind.lower(), size, f"zgrajeno {s['built']}" if s["built"] else "") if x)
        return (f'<tr><td class="d">{day(s["day"])}</td><td class="k">{kind}</td><td class="a">{esc(where(s))}</td>'
                f'<td class="n s">{size}</td><td class="n y">{s["built"] or "–"}</td><td class="n p"><b>{eur(s["price"])}</b></td>'
                f'<td class="n m">{eur(per_m2(s))}/m²</td><td class="meta">{meta}</td></tr>')
    more = (f'<p class="note">Prikazanih je zadnjih {len(shown)} od {len(rows)} prodaj; vse najdete na straneh posameznih ulic in krajev.</p>'
            if note and len(shown) < len(rows) else "")
    return f"""<h2>{title}</h2><div class="scroll"><table class="sales">
<thead><tr><th>Datum</th><th>Vrsta</th><th>Naslov</th><th class="n">Velikost</th><th class="n">Zgrajeno</th><th class="n">Cena</th><th class="n">Na m²</th><th class="meta"></th></tr></thead>
<tbody>{''.join(row(s) for s in shown)}</tbody></table></div>{more}"""


def intro(where, rows):
    return f'<p class="lead">{sold(len(rows))} stanovanj in hiš {esc(where)} od {day(rows[-1]["day"])} do {day(rows[0]["day"])}.</p>'


def write(out, path, content, name="index.html"):
    target = out / path / name if path else out / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# ---------- whole-site pages ----------

MAP_BINS = (1500, 2500, 3500, 4500, 5500)                                 # €/m² class breaks, kept in step with map.js
MAP_COLORS = ("#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")  # one-hue blue ramp, light -> dark

FAQ = (
    ("Od kod so podatki?",
     "Iz Evidence trga nepremičnin, ki jo vodi Geodetska uprava RS. Vanjo morajo biti vpisani vsi kupoprodajni posli, "
     "podatki pa so javni. Stran jih prenese vsak teden."),
    ("Zakaj moje prodaje ni na seznamu?",
     "Prodaje se v evidenci pojavijo z nekajmesečnim zamikom. Upoštevane so le tržne prodaje enega celega stanovanja ali hiše "
     "(skupaj z garažo ali shrambo). Prodaje deležev, več stanovanj hkrati, prodaje v družini in prodaje daleč pod običajno "
     "ceno v občini so izpuščene."),
    ("Kaj pomeni mediana?",
     "Sredinska vrednost: polovica prodaj je bila dražja, polovica cenejša. Za razliko od povprečja je posamezna zelo draga ali "
     "zelo poceni prodaja ne premakne."),
    ("Ali cena hiše vključuje zemljišče?",
     "Da. Prikazana je celotna pogodbena cena, zato je cena hiše na m² višja, kot bi bila za samo stavbo, posebej pri velikih parcelah."),
    ("Zakaj ni številke stanovanja?",
     "Zaradi zasebnosti. Prikazana sta ulica in hišna številka, prodaja pa ni povezana z določenim stanovanjem. "
     "Kupci in prodajalci v javnih podatkih niso navedeni."),
)


def faq():
    return "<h2>Pogosta vprašanja</h2>" + "".join(
        f'<details class="faq"><summary>{q}</summary><p>{a}</p></details>' for q, a in FAQ)


def home(rows, stats, munis):
    return page(
        "", "Prodajne cene stanovanj in hiš v Sloveniji – cenenepremicnin.si",
        "Dejanske prodajne cene stanovanj in hiš v Sloveniji po ulicah, krajih in občinah, iz uradne evidence trga nepremičnin. Brezplačno.",
        f"""<h1>Prodajne cene stanovanj in hiš v Sloveniji</h1>
<p class="lead">Za koliko so se stanovanja in hiše dejansko prodala, po ulicah, krajih in občinah:
{sold(len(rows))} od {day(rows[-1]['day'])} do {day(rows[0]['day'])}, iz uradne evidence Geodetske uprave.</p>
<form class="big-search" action="/" role="search"><input id="q" name="q" type="search" autocomplete="off"
placeholder="Vpišite ulico, kraj ali občino, npr. Celovška cesta" aria-label="Iskanje"></form>
<ul id="results" class="results"></ul>
<p class="maplink"><a href="/zemljevid/">Vse prodaje na zemljevidu →</a></p>
{figures(stats)}
{trend([("Stanovanja", rows, "stanovanje"), ("Hiše", rows, "hisa")])}
{sale_table(rows, True, 15, "Zadnje vpisane prodaje", note=False)}
{places('Občine', munis)}
{faq()}""",
        scripts="")


def map_page(rows):
    years = sorted({s["day"][:4] for s in rows}, reverse=True)
    options = "".join(f'<option value="{y}">{y}</option>' for y in years)
    bounds = ("do " + num(MAP_BINS[0]),) + tuple(f"{num(a)}–{num(b)}" for a, b in zip(MAP_BINS, MAP_BINS[1:])) + (num(MAP_BINS[-1]) + " in več",)
    legend = "".join(f'<span><i style="background:{c}"></i>{b}</span>' for c, b in zip(MAP_COLORS, bounds))
    return page(
        "zemljevid/", "Zemljevid prodaj stanovanj in hiš – cenenepremicnin.si",
        "Zemljevid dejanskih prodaj stanovanj in hiš v Sloveniji: vsaka stavba s ceno na m² in seznamom prodaj.",
        f"""<h1>Zemljevid prodaj</h1>
<p class="lead">Vsaka pika je stavba, v kateri je bilo prodano stanovanje ali hiša. Barva pove mediano cene na m²; kliknite piko za seznam prodaj.</p>
<div class="controls">
<label>Vrsta <select id="kind"><option value="">Stanovanja in hiše</option><option value="0">Stanovanja</option><option value="1">Hiše</option></select></label>
<label>Obdobje <select id="period"><option value="">Vsa leta</option><option value="12">Zadnjih 12 mesecev</option>{options}</select></label>
<span id="count" class="note"></span></div>
<div id="map" class="map"></div>
<p class="map-legend"><b>€ na m²</b> {legend}</p>""",
        head='\n<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css">',
        scripts=f'\n<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>\n<script src="{asset("map.js")}" defer></script>')


def map_data(rows):
    """map.json: {"paths": [...], "buildings": [[lon, lat, path index, address, [[day, 0 flat / 1 house, m², €], ...]], ...]}"""
    paths, index, buildings = [], {}, {}
    for s in rows:
        if not s["at"]:
            continue
        b = buildings.get(s["at"])
        if b is None:
            path = f"{slug(s['municipality'])}/{slug(s['town'])}/" + (f"{slug(s['street'])}/" if s["street"] else "")
            if path not in index:
                index[path] = len(paths)
                paths.append(path)
            addr = ", ".join(x for x in (f"{s['street'] or ''} {s['number']}".strip(), s["town"]) if x)
            b = buildings[s["at"]] = [s["at"][1], s["at"][0], index[path], addr, []]
        b[4].append([s["day"], 0 if s["kind"] == "stanovanje" else 1, s["area"], s["price"]])
    return json.dumps({"paths": paths, "buildings": list(buildings.values())}, ensure_ascii=False, separators=(",", ":"))


def rankings(rows, munis, towns, since):
    """Municipalities and towns by median €/m² over the last two years."""
    latest = date.fromisoformat(rows[0]["day"])
    two_years = date.fromordinal(latest.toordinal() - 730).isoformat()
    def ranked(items, kind, need=15):
        out = []
        for n, link, rs in items:
            v = [per_m2(s) for s in rs if s["kind"] == kind and s["day"] >= two_years]
            if len(v) >= need:
                out.append((statistics.median(v), len(v), n, link))
        return sorted(out, reverse=True)
    def table(title, items, start=1):
        body = "".join(f'<tr><td class="n">{i}.</td><th><a href="/{esc(link)}">{esc(n)}</a></th><td class="n">{eur(m)}</td><td class="n">{c}</td></tr>'
                       for i, (m, c, n, link) in enumerate(items, start))
        return f"""<h2>{title}</h2><div class="scroll"><table class="rank">
<thead><tr><th class="n">#</th><th>Ime</th><th class="n">Mediana €/m²</th><th class="n">Prodaj</th></tr></thead><tbody>{body}</tbody></table></div>"""
    town_flats = ranked(towns, "stanovanje")
    priciest = sorted((s for s in rows if s["day"] >= since), key=lambda s: -s["price"])[:20]
    return page(
        "lestvice/", "Najdražje in najcenejše občine in kraji – cenenepremicnin.si",
        "Lestvice slovenskih občin in krajev po mediani prodajne cene stanovanj in hiš na m² v zadnjih dveh letih.",
        f"""<h1>Lestvice</h1>
<p class="lead">Občine in kraji po mediani cene na m² v zadnjih dveh letih (od {day(two_years)}). Upoštevani so kraji z vsaj 15 prodajami.</p>
{table("Kraji z najdražjimi stanovanji", town_flats[:25])}
{table("Kraji z najcenejšimi stanovanji", town_flats[::-1][:25])}
{table("Občine po ceni stanovanj", ranked(munis, "stanovanje"))}
{table("Občine po ceni hiš", ranked(munis, "hisa"))}
{sale_table(priciest, True, title="Najdražje prodaje zadnjih 12 mesecev", note=False)}""")


def about_data(rows):
    return page(
        "o-podatkih/", "O podatkih – cenenepremicnin.si",
        "Od kod so podatki o prodajnih cenah nepremičnin, katere prodaje so upoštevane in kako so izračunane mediane.",
        f"""<h1>O podatkih</h1>
<div class="prose">
<p>Vse cene na tej strani so iz <a href="https://www.e-prostor.gov.si/">Evidence trga nepremičnin</a>, ki jo vodi
Geodetska uprava Republike Slovenije. V evidenco se vpisujejo vsi kupoprodajni posli z nepremičninami, podatki pa so javni
(licenca CC BY 4.0). Stran jih prenese vsak torek in prikaže prodaje od {day(rows[-1]['day'])} naprej.</p>
<h2>Katere prodaje so upoštevane</h2>
<p>Tržne prodaje enega celega stanovanja ali hiše, ki jim je lahko priložena garaža, parkirno mesto ali shramba.
Izpuščene so prodaje deležev, prodaje več stanovanj hkrati, posli, ki jih uprava ne šteje za tržne, in prodaje s ceno pod
10.000 € ali zunaj razpona od 300 do 20.000 € na m², ki so skoraj vedno napake v vpisu.</p>
<p>Prodaje družinskim članom in povezanim osebam uprava vodi posebej in niso upoštevane. Ker večina prodaj še čaka na
preverjanje, so izpuščene tudi prodaje stanovanj pod 40 % in prodaje hiš pod 30 % običajne cene na m² v isti občini:
take cene skoraj nikoli niso tržne.</p>
<h2>Kako so izračunane številke</h2>
<p>Cena na m² je pogodbena cena, deljena z uporabno površino stanovanja ali hiše (če je ni, s prodano površino).
Za kraje, ulice in leta je prikazana mediana, ne povprečje: polovica prodaj je bila dražja, polovica cenejša.
Cena hiše vključuje zemljišče, zato je njena cena na m² višja, kot bi bila za samo stavbo.</p>
<h2>Zamik</h2>
<p>Prodaja se v evidenci pojavi šele nekaj tednov ali mesecev po podpisu pogodbe, zato so zadnji meseci vedno nepopolni.</p>
<h2>Zasebnost</h2>
<p>Pri prodajah sta prikazana ulica in hišna številka, številka stanovanja pa ne, zato prodaja ni povezana z določenim
stanovanjem. Kupci in prodajalci v javnih podatkih niso navedeni. Na zemljevidu so prodaje prikazane na sredini stavbe.</p>
<h2>Omejitve</h2>
<p>Javni podatki ne vsebujejo nadstropja, števila sob ali stanja nepremičnine, zato je cena posamezne prodaje lahko
precej drugačna od mediane kraja. Podatki so informativni in niso cenitev.</p>
</div>""")


def not_found():
    return page("404.html", "Te strani ni – cenenepremicnin.si", "", """<h1>Te strani ni</h1>
<p class="lead">Morda na tej ulici v zadnjih letih ni bilo prodaj. Poiščite ulico, kraj ali občino:</p>
<form class="big-search" action="/" role="search"><input name="q" type="search" placeholder="npr. Celovška cesta" aria-label="Iskanje"></form>""",
                index=False)


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

    search, sitemap, munis, all_towns = [], [], [], []
    for m, towns in tree.items():
        m_path = f"{slug(m)}/"
        m_rows = sorted((s for t in towns.values() for st in t.values() for s in st), key=lambda s: s["day"], reverse=True)
        munis.append((m, m_path, m_rows))
        town_items = []
        for t, streets in towns.items():
            t_path = f"{m_path}{slug(t)}/"
            t_rows = sorted((s for st in streets.values() for s in st), key=lambda s: s["day"], reverse=True)
            town_items.append((t, t_path, t_rows))
            all_towns.append((t if t == m else f"{t} ({m})", t_path, t_rows))
            street_items = []
            for st_name, st_rows in streets.items():
                if not st_name:
                    continue
                st_path = f"{t_path}{slug(st_name)}/"
                street_items.append((st_name, st_path, st_rows))
                indexed = len(st_rows) >= INDEX_MIN
                where = f"{st_name}, {t}"
                kind = main_kind(st_rows)
                write(out, st_path, page(
                    st_path, f"{where}: prodajne cene stanovanj in hiš",
                    f"Za koliko so se dejansko prodala stanovanja in hiše na naslovu {where}: {sold(len(st_rows))} z datumi, velikostmi in cenami na m².",
                    f"<h1>{esc(st_name)}<small>{esc(t)}, občina {esc(m)}</small></h1>{intro('na tej ulici', st_rows)}"
                    f"{figures(summary(st_rows, since))}{comparison('na tej ulici', st_rows, f'v kraju {t}', t_rows, since)}"
                    f"{map_link(st_rows, 16)}{trend([(st_name, st_rows, kind), (t, t_rows, kind)])}"
                    f"{sale_table(st_rows, False)}{by_year(st_rows)}",
                    crumbs=((m, m_path), (t, t_path)), index=indexed))
                search.append([st_name, t, st_path, len(st_rows)])
                if indexed:
                    sitemap.append(st_path)
            listing = sale_table(t_rows, False, None if len(t_rows) <= TABLE_MAX else TABLE_MAX)
            kind = main_kind(t_rows)
            parent = (f"v občini {m}", m_rows, m) if len(t_rows) < 0.8 * len(m_rows) else ("v Sloveniji", rows, "Slovenija")
            write(out, t_path, page(
                t_path, f"{t}: prodajne cene stanovanj in hiš" + (f" ({m})" if m != t else ""),
                f"Dejanske prodajne cene nepremičnin v kraju {t}: {sold(len(t_rows))} stanovanj in hiš, cene na m² po ulicah in letih.",
                f"<h1>{esc(t)}<small>občina {esc(m)}</small></h1>{intro('v kraju ' + t, t_rows)}{figures(summary(t_rows, since))}"
                f"{comparison(f'v kraju {t}', t_rows, parent[0], parent[1], since)}{map_link(t_rows, 14)}"
                f"{trend([(t, t_rows, kind), (parent[2], parent[1], kind)])}"
                f"{places('Ulice', street_items)}{listing}{by_year(t_rows)}",
                crumbs=((m, m_path),), index=len(t_rows) >= INDEX_MIN))
            search.append([t, f"občina {m}" if m != t else "kraj", t_path, len(t_rows)])
            if len(t_rows) >= INDEX_MIN:
                sitemap.append(t_path)
        kind = main_kind(m_rows)
        write(out, m_path, page(
            m_path, f"Občina {m}: prodajne cene stanovanj in hiš",
            f"Za koliko se prodajajo stanovanja in hiše v občini {m}: {sold(len(m_rows))}, cene na m² po krajih in letih.",
            f"<h1>Občina {esc(m)}</h1>{intro('v občini ' + m, m_rows)}{figures(summary(m_rows, since))}"
            f"{comparison(f'v občini {m}', m_rows, 'v Sloveniji', rows, since)}{map_link(m_rows, 12)}"
            f"{trend([(m, m_rows, kind), ('Slovenija', rows, kind)])}"
            f"{places('Kraji', town_items)}{sale_table(m_rows, True, TABLE_MAX)}{by_year(m_rows)}"))
        search.append([m, "občina", m_path, len(m_rows)])
        sitemap.append(m_path)

    write(out, "", home(rows, summary(rows, since), munis))
    write(out, "zemljevid/", map_page(rows))
    write(out, "lestvice/", rankings(rows, munis, all_towns, since))
    write(out, "o-podatkih/", about_data(rows))
    write(out, "", not_found(), "404.html")
    sitemap[:0] = ["", "zemljevid/", "lestvice/", "o-podatkih/"]

    (out / "map.json").write_text(map_data(rows), encoding="utf-8")
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
