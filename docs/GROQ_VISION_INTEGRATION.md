# Groq Vision Integration

Groq is called only by the backend. The API key must never use a `VITE_*` variable or be included in frontend code.

Configuration:

```env
GROQ_API_KEY=
GROQ_VISION_MODEL=qwen/qwen3.6-27b
GROQ_REQUEST_TIMEOUT=45
GROQ_MAX_RETRIES=2
VISUAL_INTELLIGENCE_ENABLED=true
VISUAL_INTELLIGENCE_AUTO_ANALYZE=true
VISUAL_INTELLIGENCE_QUEUE_SIZE=64
VISUAL_INTELLIGENCE_REQUEST_INTERVAL_SECONDS=2
```

`VisionIntelligenceProvider` is the provider boundary. `GroqVisionProvider` sends the existing private JPEG crop as an inline base64 data URL, requests JSON mode, disables visible reasoning and validates the response with `VehicleVisualProfile` before persistence.

The centralized prompt version is `vehicle_visual_profile_v1`. It requires visible-only observations and prohibits identity, criminal association, cause-of-damage, unseen mechanical condition and unsupported exact make/model claims. The established ANPR result remains the primary registration value.

Requests are paced by `VISUAL_INTELLIGENCE_REQUEST_INTERVAL_SECONDS`. Retries are bounded and use exponential backoff. Pending and in-progress work is recovered after a backend restart; timeouts, rate limits, invalid JSON and schema failures are persisted without affecting the detection pipeline. Rotate `GROQ_API_KEY` through the deployment secret mechanism; never log or commit it.

The backend host needs outbound HTTPS access to Groq. Running YOLO on an offline NVIDIA host does not make the Groq API available; use an internet-enabled backend or disable automatic enrichment until connectivity is restored.
