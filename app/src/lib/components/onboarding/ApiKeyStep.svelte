<script lang="ts">
  import { Button, Input } from "$lib/components/ui";
  import { invoke } from "@tauri-apps/api/core";
  import { Command } from "@tauri-apps/plugin-shell";
  import { open } from "@tauri-apps/plugin-shell";
  import { Key, Check, ExternalLink, AlertCircle, ArrowRight, ArrowLeft, Info } from "lucide-svelte";
  import { onboardingStore } from "$lib/stores/onboarding.svelte";

  interface Props {
    onNext: () => void;
    onBack: () => void;
  }

  let { onNext, onBack }: Props = $props();

  let provider = $state(onboardingStore.state.data.api_key.provider);
  let apiKey = $state("");
  let selectedModel = $state("");
  let picoServerUrl = $state("http://localhost:11434");
  let picoModels = $state<ModelOption[]>([]);
  let picoLoading = $state(false);
  let verifying = $state(false);
  let verified = $state(onboardingStore.state.data.api_key.verified);
  let error = $state<string | null>(null);

  interface ModelOption {
    id: string;
    name: string;
    tag?: string;
  }

  interface ProviderConfig {
    id: string;
    name: string;
    description: string;
    url: string;
    keyPlaceholder: string;
    keyPrefix: string;
    envPrefixed: string;
    envStandard: string;
    isLocal?: boolean;
    models: ModelOption[];
  }

  const providers: ProviderConfig[] = [
    {
      id: "anthropic",
      name: "Anthropic (Claude)",
      description: "Claude models. Excellent tool use and instruction following.",
      url: "https://console.anthropic.com/settings/keys",
      keyPlaceholder: "sk-ant-api03-...",
      keyPrefix: "sk-ant-",
      envPrefixed: "MACBOT_ANTHROPIC_API_KEY",
      envStandard: "ANTHROPIC_API_KEY",
      models: [
        { id: "anthropic/claude-sonnet-4-5", name: "Claude Sonnet 4.5", tag: "Recommended" },
        { id: "anthropic/claude-opus-4-6", name: "Claude Opus 4.6", tag: "Most capable" },
        { id: "anthropic/claude-haiku-4-5", name: "Claude Haiku 4.5", tag: "Fast & cheap" },
      ],
    },
    {
      id: "openai",
      name: "OpenAI (GPT-5)",
      description: "GPT-5 series and reasoning models from the makers of ChatGPT.",
      url: "https://platform.openai.com/api-keys",
      keyPlaceholder: "sk-proj-...",
      keyPrefix: "sk-",
      envPrefixed: "MACBOT_OPENAI_API_KEY",
      envStandard: "OPENAI_API_KEY",
      models: [
        { id: "openai/gpt-5.2", name: "GPT-5.2", tag: "Recommended" },
        { id: "openai/gpt-5.2-pro", name: "GPT-5.2 Pro", tag: "Most capable" },
        { id: "openai/gpt-5.1", name: "GPT-5.1" },
        { id: "openai/gpt-5-mini", name: "GPT-5 Mini", tag: "Fast & cheap" },
        { id: "openai/o4-mini", name: "o4-mini", tag: "Reasoning" },
      ],
    },
    {
      id: "openrouter",
      name: "OpenRouter",
      description: "Access many models (DeepSeek, Gemini, GLM, Llama) with one key.",
      url: "https://openrouter.ai/keys",
      keyPlaceholder: "sk-or-v1-...",
      keyPrefix: "sk-or-",
      envPrefixed: "MACBOT_OPENROUTER_API_KEY",
      envStandard: "OPENROUTER_API_KEY",
      models: [
        { id: "openrouter/deepseek/deepseek-v3.2-20251201", name: "DeepSeek V3.2", tag: "Recommended" },
        { id: "openrouter/google/gemini-2.5-flash", name: "Gemini 2.5 Flash", tag: "Fast & cheap" },
        { id: "openrouter/google/gemini-2.5-pro", name: "Gemini 2.5 Pro" },
        { id: "openrouter/z-ai/glm-4.7-20251222", name: "GLM 4.7" },
        { id: "openrouter/meta-llama/llama-4-maverick-17b-128e-instruct", name: "Llama 4 Maverick" },
        { id: "openrouter/qwen/qwen3-235b-a22b-04-28", name: "Qwen 3 235B" },
        { id: "openrouter/x-ai/grok-4.1-fast", name: "Grok 4.1 Fast" },
        { id: "openrouter/deepseek/deepseek-r1:free", name: "DeepSeek R1", tag: "Free · Reasoning" },
        { id: "openrouter/meta-llama/llama-3.3-70b-instruct:free", name: "Llama 3.3 70B", tag: "Free · All-rounder" },
        { id: "openrouter/google/gemini-2.0-flash-lite-preview-02-05:free", name: "Gemini 2.0 Flash Lite", tag: "Free · Fast" },
        { id: "openrouter/qwen/qwen3-next-80b-a3b-instruct:free", name: "Qwen 3 Next 80B", tag: "Free · Coding" },
        { id: "openrouter/openrouter/auto:free", name: "Auto (Free Router)", tag: "Free · Auto" },
      ],
    },
    {
      id: "pico",
      name: "Pico AI Server (Local)",
      description: "Run models locally on your Mac. No API key needed.",
      url: "https://apps.apple.com/app/pico-ai-server/id6502491545",
      keyPlaceholder: "",
      keyPrefix: "",
      envPrefixed: "",
      envStandard: "",
      isLocal: true,
      models: [
        { id: "pico/llama3.2", name: "Llama 3.2", tag: "Recommended" },
        { id: "pico/deepseek-r1:8b", name: "DeepSeek R1 8B", tag: "Reasoning" },
        { id: "pico/gemma3", name: "Gemma 3" },
        { id: "pico/qwen2.5", name: "Qwen 2.5" },
      ],
    },
  ];

  const currentProvider = $derived(providers.find((p) => p.id === provider)!);
  const currentModels = $derived(
    provider === "pico" && picoModels.length > 0
      ? picoModels
      : currentProvider.models,
  );

  async function fetchPicoModels(serverUrl: string) {
    picoLoading = true;
    try {
      const resp = await fetch(`${serverUrl}/api/tags`);
      if (!resp.ok) return;
      const data = await resp.json();
      const models: ModelOption[] = (data.models ?? []).map((m: { name: string }) => ({
        id: `pico/${m.name}`,
        name: m.name,
      }));
      if (models.length > 0) {
        picoModels = models;
      }
    } catch {
      // Server unreachable — keep hardcoded fallback
    } finally {
      picoLoading = false;
    }
  }

  // Discover Pico models when provider is selected
  $effect(() => {
    if (provider === "pico") {
      fetchPicoModels(picoServerUrl);
    }
  });

  // Set default model when provider changes
  $effect(() => {
    const models = provider === "pico" && picoModels.length > 0
      ? picoModels
      : currentProvider.models;
    if (models.length > 0 && (!selectedModel || !models.some((m) => m.id === selectedModel))) {
      selectedModel = models[0].id;
    }
  });

  function providerDisplayName(): string {
    if (provider === "anthropic") return "Anthropic";
    if (provider === "openai") return "OpenAI";
    if (provider === "pico") return "Pico";
    return "OpenRouter";
  }

  function modelDisplayName(): string {
    const m = currentModels.find((m) => m.id === selectedModel);
    return m?.name ?? selectedModel;
  }

  async function openProviderSite() {
    await open(currentProvider.url);
  }

  async function verifyKey() {
    if (!currentProvider.isLocal && !apiKey.trim()) {
      error = "Please enter your API key in the field above";
      return;
    }

    verifying = true;
    error = null;

    try {
      if (currentProvider.isLocal) {
        // Pico: validate server connectivity
        try {
          const resp = await fetch(`${picoServerUrl}/api/tags`);
          if (!resp.ok) throw new Error(`Server returned ${resp.status}`);
        } catch (e) {
          error = `Cannot connect to Pico server at ${picoServerUrl}. Make sure Pico AI Server is running.`;
          verifying = false;
          return;
        }
      } else {
        // Validate key format
        const keyRegex = new RegExp(`^${currentProvider.keyPrefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`);
        if (!keyRegex.test(apiKey)) {
          error = `This doesn't look like a valid ${providerDisplayName()} API key. It should start with "${currentProvider.keyPrefix}"`;
          verifying = false;
          return;
        }
      }

      // Read existing config
      let config = await invoke<string>("read_config");

      // Remove all old API key, model, and Pico lines
      const lines = config.split("\n").filter((line) => {
        const trimmed = line.trim();
        return (
          trimmed &&
          !trimmed.startsWith("MACBOT_ANTHROPIC_API_KEY=") &&
          !trimmed.startsWith("MACBOT_OPENAI_API_KEY=") &&
          !trimmed.startsWith("MACBOT_OPENROUTER_API_KEY=") &&
          !trimmed.startsWith("ANTHROPIC_API_KEY=") &&
          !trimmed.startsWith("OPENAI_API_KEY=") &&
          !trimmed.startsWith("OPENROUTER_API_KEY=") &&
          !trimmed.startsWith("MACBOT_PICO_API_BASE=") &&
          !trimmed.startsWith("MACBOT_MODEL=") &&
          !trimmed.startsWith("MODEL=")
        );
      });

      if (currentProvider.isLocal) {
        // Pico: save server URL and model, no API key
        lines.push(`MACBOT_PICO_API_BASE=${picoServerUrl}`);
      } else {
        // Cloud provider: save API key
        lines.push(`${currentProvider.envPrefixed}=${apiKey}`);
        lines.push(`${currentProvider.envStandard}=${apiKey}`);
      }
      lines.push(`MACBOT_MODEL=${selectedModel}`);

      await invoke("write_config", { content: lines.join("\n") + "\n" });

      // Also store API key in macOS Keychain (preferred source)
      if (!currentProvider.isLocal && apiKey.trim()) {
        try {
          const cmd = Command.create("security", [
            "add-generic-password",
            "-a", `${provider}_api_key`,
            "-s", "son-of-simon",
            "-w", apiKey.trim(),
            "-U",
          ]);
          await cmd.execute();
        } catch {
          // Keychain save is best-effort; .env write already succeeded
        }
      }

      verified = true;
      await onboardingStore.updateApiKey({
        provider,
        configured: true,
        verified: true,
      });
    } catch (e) {
      error = `Something went wrong: ${e}`;
    } finally {
      verifying = false;
    }
  }

  function handleContinue() {
    if (verified) {
      onNext();
    }
  }
</script>

<div class="flex flex-col px-10 py-8">
  <div class="flex items-center gap-3 mb-3">
    <div class="p-2 bg-primary/10 rounded-lg">
      <Key class="w-6 h-6 text-primary" />
    </div>
    <h2 class="text-2xl font-bold text-text">Connect to AI</h2>
  </div>

  <p class="text-text-muted mb-6">
    Son of Simon uses AI to understand what you want to do. You'll need an API key from an AI provider.
  </p>

  <!-- What is an API key? -->
  <div class="flex items-start gap-3 p-4 bg-bg-card rounded-xl border border-border mb-6">
    <Info class="w-5 h-5 text-primary shrink-0 mt-0.5" />
    <div>
      <p class="text-sm text-text-muted">
        <strong class="text-text">What's an API key?</strong> It's a unique code that identifies you to
        the AI service. Create an account with any provider below to get one.
        Usage is pay-as-you-go and typically costs just a few cents per day.
      </p>
    </div>
  </div>

  <!-- Provider Selection -->
  <div class="mb-6">
    <p class="text-sm font-medium text-text mb-3">Choose your AI provider:</p>
    <div class="grid gap-3">
      {#each providers as p}
        <button
          type="button"
          onclick={() => {
            provider = p.id;
            verified = false;
            error = null;
            apiKey = "";
          }}
          class="p-4 rounded-xl border text-left transition-all
                 {provider === p.id
            ? 'border-primary bg-primary/5 ring-2 ring-primary/20'
            : 'border-border bg-bg-card hover:border-text-muted'}"
        >
          <div class="flex items-center justify-between mb-1">
            <span class="font-semibold text-text">{p.name}</span>
          </div>
          <p class="text-sm text-text-muted">{p.description}</p>
        </button>
      {/each}
    </div>
  </div>

  <!-- Model Selection -->
  <div class="mb-6">
    <label for="model-select" class="text-sm font-medium text-text mb-2 block">
      Model:{#if picoLoading}<span class="text-text-muted font-normal ml-2">discovering...</span>{/if}
    </label>
    <select
      id="model-select"
      bind:value={selectedModel}
      disabled={verified || picoLoading}
      class="w-full p-3 bg-bg-input border border-border rounded-xl text-text text-sm
             focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary
             disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {#each currentModels as m}
        <option value={m.id}>
          {m.name}{m.tag ? ` — ${m.tag}` : ""}
        </option>
      {/each}
    </select>
  </div>

  {#if !verified}
    {#if currentProvider.isLocal}
      <!-- Pico Setup Instructions -->
      <div class="mb-6 p-5 bg-bg-card rounded-xl border border-border">
        <h3 class="font-semibold text-text mb-3">How to set up Pico AI Server:</h3>
        <ol class="text-sm text-text-muted space-y-2 mb-4">
          <li class="flex gap-2">
            <span class="text-primary font-medium">1.</span>
            <span>Install Pico AI Server from the Mac App Store</span>
          </li>
          <li class="flex gap-2">
            <span class="text-primary font-medium">2.</span>
            <span>Open Pico and download a model (e.g. Llama 3.2)</span>
          </li>
          <li class="flex gap-2">
            <span class="text-primary font-medium">3.</span>
            <span>Make sure the server is running, then click Save below</span>
          </li>
        </ol>
        <Button variant="secondary" onclick={openProviderSite}>
          Open Mac App Store
          <ExternalLink class="w-4 h-4" />
        </Button>
      </div>

      <!-- Server URL Input -->
      <div class="mb-6">
        <Input
          type="url"
          label="Server URL"
          placeholder="http://localhost:11434"
          bind:value={picoServerUrl}
          error={error ?? undefined}
        />
        <button
          type="button"
          class="mt-2 text-xs text-primary hover:underline"
          onclick={() => fetchPicoModels(picoServerUrl)}
          disabled={picoLoading}
        >
          {picoLoading ? "Discovering models..." : "Refresh models from server"}
        </button>
      </div>

      <!-- Save Button -->
      <Button onclick={verifyKey} loading={verifying} disabled={verifying}>
        {verifying ? "Checking server..." : "Save & Connect"}
      </Button>
    {:else}
      <!-- Get API Key Instructions -->
      <div class="mb-6 p-5 bg-bg-card rounded-xl border border-border">
        <h3 class="font-semibold text-text mb-3">How to get your API key:</h3>
        <ol class="text-sm text-text-muted space-y-2 mb-4">
          <li class="flex gap-2">
            <span class="text-primary font-medium">1.</span>
            <span>Click the button below to open {providerDisplayName()}'s website</span>
          </li>
          <li class="flex gap-2">
            <span class="text-primary font-medium">2.</span>
            <span>Create a free account or sign in</span>
          </li>
          <li class="flex gap-2">
            <span class="text-primary font-medium">3.</span>
            <span>Create a new API key and copy it</span>
          </li>
          <li class="flex gap-2">
            <span class="text-primary font-medium">4.</span>
            <span>Paste it in the field below</span>
          </li>
        </ol>
        <Button variant="secondary" onclick={openProviderSite}>
          Open {providerDisplayName()} Website
          <ExternalLink class="w-4 h-4" />
        </Button>
      </div>

      <!-- API Key Input -->
      <div class="mb-6">
        <Input
          type="password"
          label="Paste your API key here"
          placeholder={currentProvider.keyPlaceholder}
          bind:value={apiKey}
          error={error ?? undefined}
        />
      </div>

      <!-- Save Button -->
      <Button onclick={verifyKey} loading={verifying} disabled={verifying || !apiKey.trim()}>
        {verifying ? "Saving..." : "Save API Key"}
      </Button>
    {/if}
  {:else}
    <!-- Success State -->
    <div class="flex items-center gap-3 p-5 bg-success/10 rounded-xl border border-success/30 mb-6">
      <div class="w-10 h-10 rounded-full bg-success/20 flex items-center justify-center">
        <Check class="w-6 h-6 text-success" />
      </div>
      <div>
        <p class="font-semibold text-success">{currentProvider.isLocal ? "Connected to local server!" : "API key saved successfully!"}</p>
        <p class="text-sm text-text-muted">Son of Simon is now connected to {modelDisplayName()} via {providerDisplayName()}.</p>
      </div>
    </div>
  {/if}

  {#if error}
    <div class="flex items-start gap-3 mt-4 p-4 bg-error/10 rounded-xl border border-error/30">
      <AlertCircle class="w-5 h-5 text-error shrink-0 mt-0.5" />
      <div>
        <p class="font-medium text-error">There was a problem</p>
        <p class="text-sm text-text-muted">{error}</p>
      </div>
    </div>
  {/if}

  <!-- Navigation -->
  <div class="flex justify-between mt-6 pt-6 border-t border-border">
    <Button variant="ghost" onclick={onBack}>
      <ArrowLeft class="w-4 h-4" />
      Back
    </Button>
    <Button onclick={handleContinue} disabled={!verified}>
      Continue
      <ArrowRight class="w-4 h-4" />
    </Button>
  </div>
</div>
