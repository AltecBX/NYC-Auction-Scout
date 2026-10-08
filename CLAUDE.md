# NYC Auction Scout

Jerry's site for NYC Department of Finance (City Sheriff) vehicle auctions. He uses it on his phone at the yard to pick which lots are worth bidding on. Bronx (Five J's, 4825 Baldwin St) is his main location.

## How it works
- `scripts/update.py` reads https://www.nyc.gov/site/finance/vehicles/auctions.page, downloads every `auction-*.pdf`, parses rows (#, YEAR, MAKE, PLATE#, ST, VEHICLE ID, LIENHOLDER), validates each VIN check digit, decodes VINs with NHTSA vPIC (batch), and pulls model year recall and complaint counts from api.nhtsa.gov.
- Output: `data/auctions.json`. Caches: `data/vin_cache.json`, `data/model_cache.json` (model stats refresh after 30 days), `data/nhtsa_models.json` (NHTSA's model names per make and year, 30 days). Auctions older than 14 days drop off. Bump `VIN_CACHE_VERSION` when adding a vPIC field to `VPIC_KEEP`.
- A PDF is re-parsed only when its sha256 changes, or with `--force`.
- `.github/workflows/update.yml` runs it at 6:07am and 6:07pm New York and commits `data/`. Manual run: Actions tab, "Update auction lists", Run workflow.
- Site: `index.html` + `styles.css` + `app.js`, static, no build step, served by GitHub Pages from `main` root. Reads `data/auctions.json`. Stars and notes live in localStorage. `manifest.webmanifest` lets Jerry add it to his iPhone home screen.
- Raw parsed rows live in `data/raw.json`; cars are rebuilt from caches on every run, so new photos and stats show up without re-reading PDFs.
- Stock photos (`find_photo` in update.py, `scripts/view_check.py`): Wikimedia Commons file whose title has the model year right before the make or model (photo dates in titles never count). Rejects interior, rear, detail shots by title, categories and description, sibling models (Accord Crosstour for Accord, via vPIC model list), body clashes (wagon for a sedan), and other generations when Commons categories say so. Prefers US cars; models with a separate Wikipedia "(North America)" article must show a US car. Tries exact year, then up to 2 years away, then overseas versions, then the Wikipedia lead photo. A CLIP model (open_clip ViT-B-32, CPU, installed in the workflow) must call the picture a front view; side or rear only as a last resort. Card caption says which year the photo is. Credit line (author, license) is shown under Details, keep it. `PHOTO_BUDGET` and `PHOTO_MINUTES` cap each run; bump `PHOTO_VERSION` to redo all picks.
- Test photo picks without saving: Actions, "Update auction lists", Run workflow, fill photo_test like `2014|Nissan|Pathfinder|SUV,2013|Toyota|Sienna|Minivan`. The log prints every candidate and why it was kept or dropped.
- Wikimedia rate limits: only request thumbnail widths the API returns (960px); other sizes get HTTP 429. Keep the 1s sleeps.
- NHTSA files complaints and crash ratings under its own model names (F-150 is "F-150 SUPER CREW", Lexus RX trim 350 is "RX350", BMW 330i is "3 SERIES", ProMaster 2500 is "PROMASTER", hybrids are separate). `match_names` maps each decode to NHTSA's list from api.nhtsa.gov/products/vehicle/models: exact name, then variants narrowed by series, cab type (`BodyCabType`), trim, body and drive, never a sibling model (Rogue Sport, Corolla Cross, NV200) or a different powertrain (a hybrid never gets ICE only names). Recalls use yet other names (F-150, 330I), so recalls are asked under the decoded name, the matched names and the probes, merged by campaign number. Cache keys add the NHTSA names when they differ from the decoded model. Card shows "No data" when NHTSA has no model by that name and year, and Details shows "NHTSA files as". Check matcher changes against every make and year in `data/raw.json`: print each group whose names differ from the decoded model.
- NHTSA crash stars come from api.nhtsa.gov/SafetyRatings (same names as complaints), best variant match by body and drive. Standard safety equipment comes from the vPIC decode.

## Design
- Brand: Jerry's 3D logo kit in `assets/` (chrome and enamel blue #1f5fbf, light blue #6ea2f0). Header is always dark asphalt so the chrome logo reads. Lot numbers are grease marker yellow #ffd23f, tilted. Font: Saira Semi Condensed.
- Light and dark follow the phone setting.

## Known data quirks
- NHTSA recall and complaint endpoints return HTTP 400 with a valid JSON body when there are 0 results. `http()` handles it.
- City lists contain typos in YEAR and MAKE. The VIN decode wins and the card shows a flag.
- Some rows print "VIN BLOCKED".
- A lienholder name can wrap onto a second line. The parser joins short all caps lines after a row with " / ".
- Unsold cars reappear on later lists. Cards flag "Also on ...".
- Staten Island filenames use 8 digit dates that may not match the auction date, so the date is read from the PDF text first.

## Auction rules shown on the page (from the city auctions page)
Cash only at the winning bid, no keys, as is, liens stay with the vehicle and the lienholder can repossess, remove by 5:00pm or $20/day storage, Certificate of Sale goes to DMV for title.

## Jerry's preferences for this project
- Mobile first. Most use is on an iPhone at the auction. No horizontal scroll, tap targets 36px+.
- No hyphens or em dashes in any visible text.
- Plain, short copy. No filler.
- Correctness over features. Never show guessed data (mileage, color, value) as fact. Label model level data as model level.
- Test parser changes against a known list: every VIN must pass the check digit, and lot counts must match the PDF.

## Views on the site
- This sale (one auction), All sales (every upcoming lot, filter by body or borough), Favorites (starred lots from any sale). Search with no match in the current sale switches to All sales.

## Open work (agreed with Jerry, not built yet)
- Research per auction: VIN history (old auction listings, damage photos, mileage), known expensive problems for the exact engine and transmission, overlooked value (trim, equipment), conservative price range, and a short auction day target list with walk away price. Every claim needs a dated source; no result means "history unknown". Plan: a Claude scheduled task the evening before each sale writes `data/research/<auction id>.json`, shown on a Targets tab.
- Waiting on Jerry: whether to pay for VIN history and market comps data, and whether research covers only the Bronx or every borough.
- Known photo gaps: about 10 lots (box trucks, a bus, scooters, a 1983 Oldsmobile) have no photo. A closest year photo can be the previous generation when Commons has no generation category (2014 Pathfinder shows a 2012).
