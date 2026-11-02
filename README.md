# Prodajne cene nepremičnin

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
m². Each year's file also holds older contracts registered late; only sales from the chosen years
are kept. The public files have no floor or room count.

**Privacy:** pages show street and house number but not the flat number, so a sale isn't tied
to a particular home. The register's buyers and sellers are not public and never appear.

## Pages

- `/` – search (streets, towns, municipalities; `search.json`), national figures, municipalities
- `/<municipality>/` – figures, towns, prices by year, latest 150 sales
- `/<municipality>/<town>/` – figures, streets, prices by year, sales (latest 150 in big towns)
- `/<municipality>/<town>/<street>/` – every sale on the street, prices by year

Streets or towns with fewer than 3 sales get a page marked `noindex` and are left out of
`sitemap.xml`, so search engines see only pages with real content. Set `SITE_URL` to the site's
address for canonical links and the sitemap.

About 11,000 files: under Cloudflare Pages' 20,000-file limit per deployment.

## Publishing

`.github/workflows/build.yml` rebuilds the site every Tuesday morning (GURS updates weekly), on a
manual run, and when the code changes, and publishes `public/` to the Cloudflare Pages project
`cene-nepremicnin` (created on the first run). It needs the repository secrets
`CLOUDFLARE_API_TOKEN` (permission Account → Cloudflare Pages → Edit) and `CLOUDFLARE_ACCOUNT_ID`.

The site is then at `cene-nepremicnin.pages.dev`. For `cene-nepremicnin.si`: add the domain to
Cloudflare (Websites → Add a site, free plan), set the nameservers it gives at the .si registrar,
then Workers & Pages → cene-nepremicnin → Custom domains → add `cene-nepremicnin.si` (and `www`).
Finally submit `https://cene-nepremicnin.si/sitemap.xml` in Google Search Console.
