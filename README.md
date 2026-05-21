# Scout — MLB Pitching & Lineup Analysis

> A quantitative MLB analytics dashboard built for front office evaluation use cases.
> Demonstrates advanced Statcast analytics, pitching profile construction, and lineup
> matchup modeling using the same public data sources used by major league teams.

## What It Does

Scout builds a complete analytical picture of a single MLB game: two starting pitchers,
two starting lineups, and a set of deterministic projections. It surfaces pitch-level
Statcast data, FanGraphs leaderboard metrics, platoon splits, and per-batter matchup scores
in a dashboard designed for front office evaluators and analytics reviewers.

## Metrics Explained

| Metric | Description |
|---|---|
| **xFIP** | Expected Fielding Independent Pitching. Normalizes home run rate to league average. A lower number indicates true talent better than ERA suggests. |
| **SIERA** | Skill-Interactive ERA. Accounts for groundball/flyball mix; best long-run ERA predictor. |
| **BABIP** | Batting Average on Balls in Play. Pitcher BABIP near .300 is sustainable; extremes suggest luck. |
| **xwOBA** | Expected wOBA based on exit velocity and launch angle. Removes sequencing and park luck. |
| **Barrel%** | % of batted balls classified as barreled. Highest single-metric correlate of hard contact. |
| **SwStr%** | Swinging strike rate. Best single metric for pitch stuff quality. |
| **K-BB%** | Strikeout minus walk rate. Combines command and stuff into one efficiency number. |
| **Matchup Score** | 1–10 score for a batter vs. starter: xwOBA (40%), contact profile (20%), barrel power (30%), platoon advantage (10%). |

## Data Sources

- **MLB Stats API** — schedule, probable starters, confirmed lineups (free, no key required)
- **Baseball Savant / Statcast** — pitch-level and batted-ball data via pybaseball
- **FanGraphs** — individual season leaderboards (xFIP, SIERA, wRC+, Barrel%) via pybaseball

## Setup

```bash
git clone <repo-url>
cd mlb-scout
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

No `.env` file required. All data sources are free and public.

## Architecture

```
mlb-scout/
├── app.py                    # Streamlit entrypoint and navigation
├── requirements.txt
├── data/cache/               # Parquet cache files (gitignored)
└── src/
    ├── data/
    │   ├── cache.py          # Disk parquet cache with TTL
    │   ├── mlb_schedule.py   # Schedule + starters + lineups
    │   └── statcast.py       # pybaseball wrappers
    ├── models/
    │   ├── pitcher_profile.py  # Pitch mix, trends, platoon splits, projections
    │   ├── lineup_analysis.py  # Matchup scores and lineup aggregates
    │   └── game_preview.py     # Combined game prediction dict
    └── ui/
        ├── game_selector.py    # Sidebar date/game picker
        ├── pitcher_page.py     # Full pitcher deep-dive
        ├── lineup_page.py      # Lineup analysis with spray charts
        └── prediction_panel.py # Top-level game summary
```

## Running Tests

```bash
pytest tests/ -v
```

<details>
<summary>Interview Talking Points</summary>

**On xFIP vs. ERA:**
> "ERA includes unearned runs, sequencing luck, and defense. xFIP strips all of that out and
> normalizes home run rate to league average. When a pitcher's xFIP is 3.40 but ERA is 4.80,
> that's a buyable asset — the ERA is likely inflating. This is the core of how teams identify
> undervalued rotation depth."

**On BABIP regression:**
> "A pitcher holding a .220 BABIP is getting beaten up by bad luck — fielders are dropping balls.
> His true ERA should be lower. A pitcher at .340 BABIP has been beating contact luck. Savant's
> expected stats quantify this explicitly. I built a gauge visualization that makes this signal
> immediately readable to non-statisticians."

**On platoon splits:**
> "A pitcher with a big platoon split — dominant vs. RHH but hittable vs. LHH — is exposed
> when a lineup stacks left-handed bats. The lineup matchup score accounts for this by giving a
> platoon advantage bonus to batters who face the opposite-handed pitcher. This is directly
> relevant to lineup construction decisions."

**On barrel rate:**
> "Barrel rate is the highest-correlation single metric for offensive damage. A 12% barrel rate
> reliably predicts power output regardless of BABIP or sequencing luck. I use it as the primary
> power signal in the matchup scoring model."

**On projection confidence:**
> "Every projection in this app has a confidence tier (High / Medium / Low) based on sample size
> and metric availability. A pitcher with 10 IP has wide variance in any projection. I surface this
> explicitly rather than hiding the uncertainty — that's the honest way to present a model to
> decision-makers."

**On the tech choices:**
> "I used pybaseball's Statcast wrapper because it mirrors what Baseball Savant surfaces publicly.
> The data pipeline uses a disk-backed parquet cache to avoid re-fetching Statcast data on every
> page load — Statcast queries can take 10–15 seconds, which is unacceptable for a live demo.
> Everything is open-source, deployable to Streamlit Community Cloud in two commands."

</details>
