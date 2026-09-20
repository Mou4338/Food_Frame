# Food Image Automation Agent

This tool looks at your restaurant menu (an Excel file), and for every dish
it automatically finds a good photo, checks the photo's quality, and sorts
it into one of three piles:

```
Score 80-100   ->  Auto Approved   (done automatically, no one needs to look at it)
Score 65-79    ->  Human Review    (a person quickly picks/approves/rejects the photo)
Score below 65 ->  Rejected        (you can search again or upload your own photo)
```

It searches **five free photo sources** for every dish (Pexels, Unsplash,
Pixabay, Wikimedia Commons, and a local Kaggle food-image dataset), scores
every photo the same way, and picks the best one. Everything happens
through a simple web dashboard — you don't need to know how to code to use
it day-to-day.

---

## What's new

- **Nothing meaningful stays on your computer.** Auto-approved images are
  uploaded straight to Google Drive and their local temp copies are
  deleted immediately. Human Review only ever keeps the best few
  candidates on disk (`review.top_n` in Settings, default 3) — the rest
  are scored, logged for audit, and deleted right away. The moment a
  reviewer approves or rejects an item, its local copies are deleted too.
- **Rejected items are archived, not thrown away.** Every rejected item's
  best photo is uploaded to Google Drive as an audit record — either to a
  separate `storage.rejected_drive_folder_id` folder (Settings page), or
  into the same approved folder with a `Rejected_` filename prefix.
- **Kaggle matching now requires the whole item name.** If your item is
  "Chicken Tandoori" and a dataset image is named
  "chicken_tandoori_butter.jpg", it matches (the full item name is found
  inside the dataset name) — a short, unrelated folder like "chicken"
  will not incorrectly match a longer item name.
- **No duplicate API calls.** Rows in your Excel file already marked
  "Done" are skipped, and `fetched_items.xlsx` remembers every
  already-approved dish by its normalized name across different menu
  files/runs, reusing the existing Drive link instead of re-searching.
- **Auto Approved tab** shows the item name, which source it was approved
  from, and whether it was auto- or human-approved, with a Drive link
  (not a local thumbnail, since the file no longer lives on disk).
- **Overview page** has an expanded numbers section — Searching, Approved
  (auto/human split), Human Review, Rejected, Errors, Not Found — for
  both the current run and an "All-time totals" view across every run.

---

## Part 1 — One-time setup (do this once)

You'll need a computer with **Python 3.10 or newer** installed. If you're
not sure, open a terminal (Command Prompt on Windows, Terminal on Mac) and
type `python3 --version`. If that doesn't work, download Python from
https://www.python.org/downloads/ first.

### Step 1: Open a terminal in this folder

Unzip this project somewhere on your computer, then open a terminal and
move into that folder, for example:

```bash
cd path/to/food_image_agent
```

### Step 2: Install the required packages

Copy and paste this into the terminal and press Enter:

```bash
pip install -r requirements.txt
```

This downloads everything the tool needs. It can take a few minutes the
first time.

### Step 3: Set up your free API keys

The tool searches multiple photo websites for you. Three of them
(Pexels, Unsplash, Pixabay) need a free "API key" — think of it as a
password that lets the tool search on your behalf. Wikimedia needs
nothing.

1. Find the file called `.env.example` in this folder and make a copy of
   it named exactly `.env` (no ".example" at the end).
2. Get a free key from each site below (takes 1–2 minutes each, just sign
   up with an email address):
   - Pexels: https://www.pexels.com/api/
   - Unsplash: https://unsplash.com/developers
   - Pixabay: https://pixabay.com/api/docs/
3. Open `.env` in any text editor (Notepad, TextEdit, VS Code, etc.) and
   paste each key after the matching `=` sign, for example:
   ```
   PEXELS_API_KEY=your_key_here
   ```
4. Save the file.

You can skip any of these and the tool will simply search fewer sources
for you — it won't break anything.

### Step 4 (optional): Turn on the Kaggle photo dataset

This gives the tool a large local library of food photos to search as a
fifth source, in addition to the three websites above.

1. Go to https://www.kaggle.com and create a free account.
2. Click your profile picture → **Account** → **Create New API Token**.
   This downloads a small file called `kaggle.json` with two values in it:
   a username and a key.
3. Open your `.env` file again and fill in:
   ```
   KAGGLE_DATASET_SLUG=kmader/food41
   KAGGLE_USERNAME=your_username_from_kaggle_json
   KAGGLE_KEY=your_key_from_kaggle_json
   ```
   `kmader/food41` is a large ready-made food-photo dataset — the tool will
   download it automatically the very first time it's needed (this can
   take a while and use several GB of disk space, since it's a big
   dataset). You can swap in any other Kaggle food-image dataset by
   changing the slug (the part of a Kaggle dataset's web address after
   `kaggle.com/datasets/`).

If you'd rather not use Kaggle at all, just leave these three lines blank
— the tool works fine with only the website sources.

### Step 5 (optional): Turn on AI photo checking

By default the tool checks photos using free, automatic technical
checks (blur, cropping, brightness, etc). You can optionally add an AI
model that also checks whether the photo actually *looks like the right
dish* — this makes the scoring noticeably smarter.

1. Get a free key from https://aistudio.google.com/apikey (Google Gemini).
2. Add it to your `.env` file:
   ```
   GEMINI_API_KEY=your_key_here
   ```
3. Turn it on from inside the dashboard later (Settings page → "Enable AI
   vision scoring"), or set `ai.enabled: true` in `config.yaml` if you
   prefer editing files directly.

### Step 6 (optional): Set up Google Drive, so approved photos upload there automatically

If you skip this step, approved photos are simply saved in a folder on
your own computer instead (`./approved_images`) — which is perfectly fine
for trying the tool out.

To upload straight to Google Drive instead, see the detailed Google Drive
setup notes inside `drive_uploader.py`, or ask whoever set up this project
for the `client_secret.json` file and Drive folder link.

---

## Part 2 — Running the tool

Every time you want to use the tool, open a terminal in this folder and
run:

```bash
streamlit run app.py
```

A browser tab will open automatically with the dashboard. If it doesn't,
the terminal will print a web address (usually `http://localhost:8501`)
you can copy into your browser.

### Using the dashboard

1. Go to the **Overview** page (it opens there by default).
2. Under "Start a new run", upload your menu Excel file.
   - Tell it which column has the dish names (default: `item_name`).
   - Tell it which sheet/tab to use (default: `Sheet1`).
3. Click **Start automation run**. The page will show live progress as it
   works through each dish.
4. While it runs (or once it's done), check the other pages:
   - **Human Review** — dishes that need a quick yes/no from a person.
     Pick the best of the candidate photos shown, or reject it.
   - **Rejected** — dishes with no good photo found. You can tell it to
     search again, or upload your own photo.
   - **Errors / Failed Jobs** — technical problems (a website timed out,
     etc). Usually fixed by just clicking "Retry".
   - **Auto Approved** — a read-only list of everything that was good
     enough to approve automatically.
   - **Performance** — charts showing how well each photo source is doing.
   - **Search History** — a full record of every photo the tool ever
     looked at, for double-checking its work.
   - **Settings** — change the approval thresholds, turn sources on/off,
     change image size, etc, without editing any files.
5. Use the **🌙 Dark mode** switch in the sidebar to flip between a white
   theme with blue accents and a black theme with gold accents — whichever
   is easier on your eyes.

When a run finishes, an Excel report (`processing_report.xlsx`) and a
CSV version are saved automatically in this folder, and your original
menu file is updated with a Status column and a link to each photo.

---

## What's in this folder

| File / folder | What it does |
|---|---|
| `app.py` | The dashboard you open with `streamlit run app.py` |
| `dashboard/` | One file per dashboard page |
| `pipeline.py` | Runs the five-source search + scoring for one dish |
| `retry_manager.py` | Powers the "Search Again" button |
| `sources/` | One file per photo source: Pexels, Unsplash, Pixabay, Wikimedia, Kaggle |
| `image_quality.py` | Free automatic photo-quality checks |
| `ai_evaluator.py` | Optional AI photo checking (Gemini, with Groq as a backup) |
| `scoring.py` | Combines all the checks into one final 0–100 score |
| `decision_engine.py` | The 80 / 65 approve-review-reject rule |
| `duplicate_detector.py` | Spots the same photo being picked twice |
| `image_processor.py` | Resizes/compresses the final chosen photo |
| `drive_uploader.py` | Uploads approved photos to Google Drive (or saves locally) |
| `db.py` | The database behind every dashboard page |
| `run_batch.py` / `main.py` | Command-line way to run a batch without the dashboard |
| `sheet_reader.py` | Reads your Excel file and writes results back into it |
| `report_generator.py` | Builds the Excel/CSV summary report |
| `config.py` / `config.yaml.example` | All the adjustable settings |
| `.env.example` | Where your API keys and secrets go (copy to `.env`) |

## Deploying (e.g. Streamlit Community Cloud)

A deployed app has no `.env` file, no local disk to keep `client_secret.json`
or `token.json` on between restarts, and no browser to complete an
interactive Google login. Use Streamlit's own **Secrets** manager instead
(on Streamlit Community Cloud: your app -> Settings -> Secrets):

1. Paste in the same keys you'd normally put in `.env`, flat, e.g.:
   ```toml
   PEXELS_API_KEY = "..."
   UNSPLASH_ACCESS_KEY = "..."
   PIXABAY_API_KEY = "..."
   GEMINI_API_KEY = "..."
   GROQ_API_KEY = "..."
   ```
   These are copied into the app's environment automatically at startup —
   no code changes needed, and everything (including the background
   `run_batch.py` process the dashboard launches) picks them up exactly
   like it would from a real `.env`.
2. For Google Drive, run this **once, locally, on your own laptop** (never
   on the server — it needs a real browser):
   ```bash
   python generate_drive_token.py client_secret.json
   ```
   Log in with the Google account that owns (or has Editor access to) your
   Drive folder. It prints a ready-to-paste `[drive_token]` block — paste
   that into the same Secrets manager, under your other keys. From then on,
   Drive logs in headlessly using that saved refresh token; the app never
   needs `client_secret.json` or a browser again.
3. Set `storage.drive_folder_id` in `config.yaml` (or the Settings page) to
   a folder that Google account can actually see — open the folder's own
   link while logged into that account to confirm before deploying.

## Troubleshooting

- **"Could not find a column named ..."** — double-check the food-name
  column name you typed matches your Excel file exactly (it's
  case-sensitive).
- **A run doesn't seem to start** — open the "View last run's log"
  expander on the Overview page; it shows the raw output of the
  background process, which usually explains what went wrong.
- **A source is always failing** — check its API key in `.env` is correct
  and hasn't expired; a missing/incorrect key shows up as errors for just
  that source, the others keep working normally.
- **Kaggle source finds nothing** — the very first search after setting
  `KAGGLE_DATASET_SLUG` can be slow (it's downloading the whole dataset).
  Give it a few minutes and try again.
