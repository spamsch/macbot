---
id: image_generation
name: Image Generation
description: Generate images from text descriptions using models with native image generation (e.g. Gemini).
apps: []
tasks: []
essential_tasks: []
examples:
  - "Generate an image of a sunset over mountains"
  - "Create a picture of a cartoon cat wearing a hat"
  - "Draw a logo for my coffee shop"
  - "Make an illustration of a futuristic city"
safe_defaults: {}
confirm_before_write: []
requires_permissions: []
---

## Behavior Notes

This skill exists as a **routing target** for intent-based pre-routing. It has no tools of its own — the routed model (e.g. Gemini) handles image generation natively.

### How It Works

1. Add a route in **Hybrid Routing** with this skill selected.
2. Set **keywords** like `generate image`, `create picture`, `draw` on the route.
3. Pick a model that supports native image generation (e.g. `gemini/gemini-2.5-flash`).
4. When the user's message matches a keyword, the agent pre-routes to that model before the first LLM call.

### Supported Models

- **Google Gemini** (`gemini/gemini-2.5-flash`, `gemini/gemini-2.5-pro`) — native image generation via the Gemini API.
