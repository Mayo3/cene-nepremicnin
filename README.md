# cenenepremicnin.si

A static website showing what flats and houses actually sold for in Slovenia, with a page for
every municipality, town and street. Listing sites show asking prices; this shows sale prices.

```sh
python build.py              # downloads GURS sales of the last 6 years, writes public/
python build.py out 3        # other folder, last 3 years
cd public && python -m http.server 8765   # preview at http://localhost:8765
```

Standard library only (Python 3.12+). Downloads are cached in `data/` for six days; a build takes
about half a minute once they are cached.

## Data

GURS, *Evidenca trga nepremičnin* (Javni geodetski podatki): public data under CC BY 4.0, which
allows commercial use with the source credited (every page's footer does this). Updated weekly,
with sales appearing a few months after the contract.

Kept: open-market sales of exactly one whole flat or house (a garage, parking space or storage
room may be included), with a price of at least €10.000, at least 12 m², and €300 to €20.000 per
m². Sales to family members are a separate deal type in the register and are left out; because most
sales are still marked "being checked", flats below 40% and houses below 30% of the municipality's
median €/m² are also left out (`CHEAP` in `build.py`). Each year's file also holds older contracts
registered late; only sales from the chosen years are kept. The public files have no floor or room
count.

**Privacy:** pages show street and house number but not the flat number, so a sale isn't tied
to a particular home. The register's buyers and sellers are not public and never appear.

## Pages

- `/` – search (streets, towns, municipalities; `search.json`), national figures and price chart,
  latest sales, municipalities, FAQ
- `/<municipality>/` – figures, comparison with Slovenia, price chart, towns, latest 150 sales
- `/<municipality>/<town>/` – figures, comparison with the municipality, price chart, streets, sales
  (latest 150 in big towns)
- `/<municipality>/<town>/<street>/` – every sale on the street, comparison with the town, price chart
- `/zemljevid/` – map and list of sales, filtered by place, kind, year, size and price. Filters are kept
  in the address (`?kje=koper/&vrsta=0&leto=2026&m2od=40&m2do=50`), so a search can be shared and place
  pages link to theirs. Dots are coloured by €/m² (`map.json`, `search.json`, `static/map.js`; MapLibre
  with OpenFreeMap tiles, free and keyless). A building's details show its Street View photo when
  `STREETVIEW_KEY` is set at build time, otherwise no photo. Sale tables on all pages
  have the same photo behind a "Slika" button on each row (`static/photo.js`)
- `/lestvice/` – municipalities and towns ranked by €/m² over the last two years
- `/o-podatkih/` – where the data comes from and what is left out

Price charts are inline SVG drawn by `build.py` (by quarter where a place has 200+ sales, else by
year). Headings use Source Serif 4, self-hosted in `static/fonts/` (SIL Open Font License).

Streets or towns with fewer than 3 sales get a page marked `noindex` and are left out of
`sitemap.xml`, so search engines see only pages with real content. Set `SITE_URL` to the site's
address for canonical links and the sitemap.

About 11,000 files: under Cloudflare Pages' 20,000-file limit per deployment.

## Publishing

`.github/workflows/build.yml` rebuilds the site every Tuesday morning (GURS updates weekly), on a
manual run, and when the code changes, and publishes `public/` to the Cloudflare Pages project
`cenenepremicnin` (created on the first run). It needs the repository secrets
`CLOUDFLARE_API_TOKEN` (permission Account → Cloudflare Pages → Edit) and `CLOUDFLARE_ACCOUNT_ID`.

For building photos, also add the secret `STREETVIEW_KEY`: a Google Cloud API key with the Street View
Static API enabled. The key is visible in the page, so restrict it to the API and to the site's
address, and set a daily quota in Google Cloud so that costs can't run away.

The site is then at `cenenepremicnin.pages.dev`. For `cenenepremicnin.si`: add the domain to
Cloudflare (Websites → Add a site, free plan), set the nameservers it gives at the .si registrar,
then Workers & Pages → cenenepremicnin → Custom domains → add `cenenepremicnin.si` (and `www`).
Finally submit `https://cenenepremicnin.si/sitemap.xml` in Google Search Console.
