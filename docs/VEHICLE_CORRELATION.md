# Vehicle Correlation Baseline

The baseline score is intentionally explainable:

| Signal | Weight | Meaning |
| --- | ---: | --- |
| Confusion-aware plate similarity | 0.50 | Normalized edit similarity with reduced cost for known OCR confusions |
| OCR confidence | 0.15 | Confidence produced by the recognition pipeline |
| Temporal feasibility | 0.15 | Whether elapsed time can cover camera separation |
| Route feasibility | 0.10 | Current baseline mirrors temporal feasibility until verified road routing is available |
| Vehicle appearance | 0.10 | Upstream similarity when supplied; otherwise a neutral 0.5 |

Transitions requiring more than 160 km/h are rejected. Those requiring 110–160 km/h
receive a severe penalty. Scores below 0.60 are rejected; 0.60–0.72 remain candidates;
0.72–0.86 are probable; confirmed requires at least 0.86 and strong plate similarity.

These thresholds are a transparent starting point, not learned probabilities. Calibrate
them on held-out local traffic data and report precision/recall separately for day,
night, rain, blur, plate style, camera, and district. Never tune on the final test split.
