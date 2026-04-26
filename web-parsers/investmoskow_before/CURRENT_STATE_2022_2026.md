# Current State 2022-2026

## Data

- Main merged dataset: `data/investmoscow_completed_2022_2026_geocoded.csv`
- Map-ready dataset: `data/investmoscow_completed_2022_2026_geocoded_mapped.csv`
- Total lots: `9595`
- Lots with coordinates: `9500`

## Year Coverage

- `2022`: `1872`
- `2023`: `2489`
- `2024`: `2395`
- `2025`: `2226`
- `2026`: `613`

## Current Pipeline

- `parser_completed_2022_2023.py` builds the 2022-2023 raw CSV and API cache
- `parser_completed_2024.py` builds the 2024 raw CSV and API cache
- `parser_completed.py` builds the 2025-2026 raw CSV
- `geocode_2022_2024.py` runs the 2022-2024 backfill entrypoint
- `backfill_geocodes_2022_2024.py` fills 2022-2024 coordinates primarily from API caches, then local fallbacks
- `geocode_addresses.py` remains the geocoder used for the 2025-2026 dataset
- `merge_all_years.py` merges 2022-2024 and 2025-2026 into the final 2022-2026 datasets
- `analyze_all_data.py` reads `data/investmoscow_completed_2022_2026_geocoded.csv`
- `app_map.py` reads `data/investmoscow_completed_2022_2026_geocoded_mapped.csv` by default

## Notes

- For `2022-2024`, the primary source of coordinates is not external geocoding but the cached API fields in:
  - `data/all_tenders_cache_2022_2023.json`
  - `data/all_tenders_cache_2024.json`
- The map app keeps fallbacks to older files, but the intended current source is the merged 2022-2026 dataset.
