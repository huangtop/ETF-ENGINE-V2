# US ETF coverage

The initial US universe covers broad market, style, international, dividend, covered-call, bonds, Treasuries, gold, REITs, sectors, semiconductors, thematic and digital-asset strategy products.

The daily workflow reads the official Nasdaq Trader symbol directories before
the price pipeline runs. The first `sync-us-entities` run establishes a market
baseline; later runs with `--apply-new` enroll only relevant AI/technology and
broad-market ETF symbols first seen after that snapshot. Leveraged, inverse,
single-stock, and unrelated products remain in the candidate audit instead of
being enrolled. This avoids importing thousands of products into the curated
universe while ensuring relevant future launches are not missed.

Newly enrolled funds receive safe placeholder research metadata and an English
display-name fallback. Their asset class, benchmark, Chinese name, and thematic
tags should subsequently be reviewed. To add or refine a fund manually, update
its entity and independent classification rows; no category file or Python code
change is required.
