# NYC Auction Scout

Jerry's site for NYC Department of Finance (City Sheriff) vehicle auctions. He uses it on his phone at the yard to pick which lots are worth bidding on. Bronx (Five J's, 4825 Baldwin St) is his main location.

## How it works
- `scripts/update.py` reads https://www.nyc.gov/site/finance/vehicles/auctions.page, downloads every `auction-*.pdf`, parses rows (#, YEAR, MAKE, PLATE#, ST, VEHICLE ID, LIENHOLDER), validates each VIN check digit, decodes VINs with NHTSA vPIC (batch), and pulls model year recall and complaint counts from api.nhtsa.gov.
- Output: `data/auctions.json`. Caches: `data/vin_cache.json`, `data/model_cache.json` (model stats refresh after 30 days). Auctions older than 14 days drop off.
- A PDF is re-parsed only when its sha256 changes, or with `--force`.
- `.github/workflows/update.yml` runs it at 6:07am and 6:07pm New York and commits `data/`. Manual run: Actions tab, "Update auction lists", Run workflow.
- `index.html` is the whole site: static, no build step, served by GitHub Pages from `main` root. Reads `data/auctions.json`. Stars and notes live in localStorage.

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
