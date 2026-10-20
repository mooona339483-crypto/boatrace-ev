# BOAT RACE EV Cloud — starter skeleton

This is a **safe, local SQLite recording engine**, not a working 24-venue scraper, probability model, or production cloud service. No wagers are placed.

Requires Python 3.10+.

```
python app.py report
```

For a validated model and documented timestamped pre-deadline odds only:

```
python app.py record --venue 18 --date 2026-10-21 --race 1 --type 2T --selection 1-2 --stake 1000 --odds 4.2 --probability 0.3 --deadline 2026-10-21T10:30:00+09:00 --source 'official odds captured at YYYY-MM-DDTHH:MM+09:00' --model 'validated-v1' --verified
```

`--verified` is an explicit operator assertion, not a substitute for actual model validation. Never use it without an out-of-sample validation record. `settle --id 1 --payout 4200` requires independently verified official settlement. `report` reports only settled bets. A single SQLite file should be on persistent storage and backed up.

## Next implementation milestones
1. Confirm official source terms and permitted automated access, especially pre-deadline odds and exhibition data.
2. Implement timestamped official ingestion, race schedules, cancellations and female-only classification.
3. Build historical train/validation/test sets with time-based separation and calibrated 2T/3T probabilities.
4. Add event-level immutable prediction snapshots, odds timestamp and model hash, with no post-deadline changes.
5. Deploy a worker and Postgres database on Railway, dashboard with authentication, backups, logging, alerting, and idempotent settlement.

Caution: `settle` currently trusts operator-entered payout and does not verify official result; it is for prototyping only. The app does not run automatically when uploaded.
