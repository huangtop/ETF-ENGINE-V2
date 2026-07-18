# Architecture

## Data layers

1. Seed: stable identifiers and manual taxonomy.
2. Provider: external source adapters only.
3. Normalized: provider-independent OHLCV and metric records.
4. Public: compact JSON contract for clients.
5. Presentation: WordPress cache and Chart.js.

Provider code must never contain fallback orchestration. `PriceService` owns provider priority and fallback.
Calculated metrics must never be written back into seed configuration.
