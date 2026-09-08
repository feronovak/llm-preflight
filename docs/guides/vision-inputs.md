# Image-to-text contract inputs

**Last reviewed:** 2026-09-08 · **As of:** v2.13.0

Use an image-to-text preflight when an application already relies on an image to
produce text: OCR, classification labels, extraction, routing, or a structured
answer. It verifies the same things as a text preflight—request compatibility,
the application's text/schema contract, latency, and reported token cost.

Start from the checked-in [Qwen Model Studio example](../../examples/vision/qwen-vl-model-studio.json)
or [Gemini example](../../examples/vision/gemini-image-to-text.json); both use
the same checked-in, non-sensitive `ORDER-4821` PNG fixture and assert that
mechanical OCR value.

It does not judge whether an image is attractive, faithful to a creative prompt,
or generally semantically good. Image-generation execution is not supported by
this release.

## Use a checked-in, non-sensitive fixture

Place a small, non-sensitive PNG, JPEG, WEBP, or GIF under the benchmark
configuration directory and reference it through `request.input_images`.

```json
{
  "prompt": "Return the invoice number as JSON.",
  "request": {
    "input_images": [
      {"path": "fixtures/invoice.png", "mime_type": "image/png"}
    ]
  }
}
```

The path must remain inside that directory. Before spending, LLM Preflight
checks its declared MIME type against the file header, records dimensions and a
SHA-256 fingerprint, and limits inputs to 10 MiB and 20 million pixels. Image
bytes are not written to result JSON.

An API caller may instead supply a strict base64 data URL such as
`data:image/png;base64,...`. It has the same MIME, byte, and pixel checks; the
resolved evidence retains only its source type and content hash, not the URL or
encoded bytes. Replay that run from the original configuration, not result JSON.

## Select a supported route

OpenRouter and an explicitly configured OpenAI-compatible endpoint use
multipart `image_url` content. Gemini uses inline image data. This lets a Qwen
image-capable Qwen model hosted through Model Studio be configured as an
`openai_compatible` model with its workspace endpoint and `DASHSCOPE_API_KEY`.

Keep the contract mechanical. For example, check an OCR response against a
JSON Schema, or require a routing label from an allowed set. Use a stable,
reviewed fixture and retain normal request and cost limits. Do not put private
customer images in a benchmark fixture or enable response retention merely to
debug a visual task. The pre-run plan deliberately reports image-input cost as
unavailable: there is no portable conversion from dimensions to billable image
tokens. A completed result reports cost only when the provider supplies usable
token usage and the model has price evidence.
