<script lang="ts">
  import { Button, Input } from "$lib/components/ui";
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-shell";
  import { Key, Check, ExternalLink, AlertCircle } from "lucide-svelte";
  import { onboardingStore } from "$lib/stores/onboarding";

  interface Props {
    onNext: () => void;
    onBack: () => void;
  }

  let { onNext, onBack }: Props = $props();

  let provider = $state(onboardingStore.state.data.api_key.provider);
  let apiKey = $state("");
  let verifying = $state(false);
  let verified = $state(onboardingStore.state.data.api_key.verified);
  let error = $state<string | null>(null);

  const providers = [
    {
      id: "anthropic",
      name: "Anthropic (Claude)",
      url: "https://console.anthropic.com/settings/keys",
      recommended: true,
    },
    {
      id: "openai",
      name: "OpenAI",
      url: "https://platform.openai.com/api-keys",
      recommended: false,
    },
  ];

  async function openProviderSite() {
    const p = providers.find((p) => p.id === provider);
    if (p) {
      await open(p.url);
    }
  }

  async function verifyKey() {
    if (!apiKey.trim()) {
      error = "Please enter an API key";
      return;
    }

    verifying = true;
    error = null;

    try {
      // Save API key to config file
      const envVar =
        provider === "anthropic" ? "ANTHROPIC_API_KEY" : "OPENAI_API_KEY";
      const model =
        provider === "anthropic"
          ? "anthropic/claude-sonnet-4-20250514"
          : "openai/gpt-4o";

      // Read existing config
      let config = await invoke<string>("read_config");

      // Update or add the API key and model
      const lines = config.split("\n").filter((line) => {
        const trimmed = line.trim();
        return (
          trimmed &&
          !trimmed.startsWith("ANTHROPIC_API_KEY=") &&
          !trimmed.startsWith("OPENAI_API_KEY=") &&
          !trimmed.startsWith("MODEL=")
        );
      });

      lines.push(`${envVar}=${apiKey}`);
      lines.push(`MODEL=${model}`);

      await invoke("write_config", { content: lines.join("\n") + "\n" });

      // TODO: Actually verify the key works by making a test API call
      // For now, we'll assume it's valid if it looks like a key
      const keyPattern =
        provider === "anthropic" ? /^sk-ant-/ : /^sk-[a-zA-Z0-9]/;

      if (!keyPattern.test(apiKey)) {
        error = `This doesn't look like a valid ${provider === "anthropic" ? "Anthropic" : "OpenAI"} API key`;
        return;
      }

      verified = true;
      await onboardingStore.updateApiKey({
        provider,
        configured: true,
        verified: true,
      });
    } catch (e) {
      error = `Failed to save API key: ${e}`;
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

<div class="flex flex-col px-8 py-6">
  <div class="flex items-center gap-3 mb-2">
    <div class="p-2 bg-primary/20 rounded-lg">
      <Key class="w-6 h-6 text-primary" />
    </div>
    <h2 class="text-2xl font-bold text-text">Connect Your AI</h2>
  </div>

  <p class="text-text-muted mb-6">
    Son of Simon uses AI to understand your commands. Connect your preferred
    provider.
  </p>

  <!-- Provider Selection -->
  <div class="mb-6">
    <label class="text-sm font-medium text-text-muted mb-2 block">
      AI Provider
    </label>
    <div class="grid grid-cols-2 gap-3">
      {#each providers as p}
        <button
          type="button"
          onclick={() => {
            provider = p.id;
            verified = false;
            error = null;
          }}
          class="p-4 rounded-lg border text-left transition-all
                 {provider === p.id
            ? 'border-primary bg-primary/10'
            : 'border-border bg-bg-card hover:border-text-muted'}"
        >
          <div class="flex items-center justify-between mb-1">
            <span class="font-medium text-text">{p.name}</span>
            {#if p.recommended}
              <span
                class="text-xs bg-primary/20 text-primary px-2 py-0.5 rounded"
              >
                Recommended
              </span>
            {/if}
          </div>
        </button>
      {/each}
    </div>
  </div>

  <!-- API Key Input -->
  <div class="mb-4">
    <Input
      type="password"
      label="API Key"
      placeholder={provider === "anthropic"
        ? "sk-ant-..."
        : "sk-..."}
      bind:value={apiKey}
      error={error ?? undefined}
      disabled={verified}
    />
  </div>

  <!-- Get API Key Link -->
  <button
    type="button"
    onclick={openProviderSite}
    class="flex items-center gap-1 text-sm text-primary hover:underline mb-6"
  >
    Don't have an API key? Get one here
    <ExternalLink class="w-3 h-3" />
  </button>

  <!-- Verify Button -->
  {#if !verified}
    <Button onclick={verifyKey} loading={verifying} disabled={verifying}>
      Verify API Key
    </Button>
  {:else}
    <div
      class="flex items-center gap-2 p-4 bg-success/10 text-success rounded-lg"
    >
      <Check class="w-5 h-5" />
      <span class="font-medium">API key verified and saved!</span>
    </div>
  {/if}

  {#if error}
    <div
      class="flex items-center gap-2 mt-4 p-4 bg-error/10 text-error rounded-lg"
    >
      <AlertCircle class="w-5 h-5 shrink-0" />
      <span class="text-sm">{error}</span>
    </div>
  {/if}

  <!-- Navigation -->
  <div class="flex justify-between mt-6 pt-6 border-t border-border">
    <Button variant="ghost" onclick={onBack}>Back</Button>
    <Button onclick={handleContinue} disabled={!verified}>Continue</Button>
  </div>
</div>
