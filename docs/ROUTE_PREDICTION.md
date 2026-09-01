# Route Prediction and Backtesting

Candidate ranking is recalculated from the latest accepted observation. Verified graph
neighbors are preferred. Otherwise the engine ranks a bounded directional cone using
distance, inferred bearing, camera readiness, and ANPR capability. Only categorical
confidence (`high`, `medium`, `low`) is shown to operators.

The prediction backtest replays each consecutive pair of accepted observations. For
every anchor it asks whether the actual next observed camera appeared at rank 1, within
the top 3, or within the top 5. Coverage records how many eligible transitions were
evaluated. Replay uses current topology and health, so reports should record the model,
graph, and registry versions used by the deployment.

Required release review:

- enough transitions to avoid unstable percentages;
- district and camera holdouts, not random adjacent video frames;
- separate results for verified topology and geospatial fallback;
- latency, candidate coverage, top-k accuracy, and coverage-gap rates;
- failure review for impossible travel, OCR confusions, offline cameras, and sparse
  corridors.
