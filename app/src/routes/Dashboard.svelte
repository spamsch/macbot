<script lang="ts">
  import { Button, LogViewer } from "$lib/components/ui";
  import { serviceStore } from "$lib/stores/service.svelte";
  import { onboardingStore } from "$lib/stores/onboarding.svelte";
  import { open } from "@tauri-apps/plugin-shell";
  import {
    Play,
    Square,
    RotateCcw,
    Settings,
    Circle,
  } from "lucide-svelte";

  let showSettings = $state(false);

  function handleStart() {
    serviceStore.start();
  }

  function handleStop() {
    serviceStore.stop();
  }

  function handleRestart() {
    serviceStore.restart();
  }

  function handleClearLogs() {
    serviceStore.clearLogs();
  }

  function toggleSettings() {
    showSettings = !showSettings;
  }
</script>

<div class="min-h-screen flex flex-col bg-bg">
  <!-- Header -->
  <header
    class="flex items-center justify-between px-6 py-4 border-b border-border bg-bg-card"
  >
    <div class="flex items-center gap-3">
      <h1 class="text-xl font-bold text-text">Son of Simon</h1>
    </div>

    <div class="flex items-center gap-4">
      <!-- Status Indicator -->
      <div class="flex items-center gap-2">
        <Circle
          class="w-3 h-3 {serviceStore.running
            ? 'fill-success text-success'
            : 'fill-text-muted text-text-muted'}"
        />
        <span class="text-sm {serviceStore.running ? 'text-success' : 'text-text-muted'}">
          {serviceStore.running ? "Running" : "Stopped"}
        </span>
      </div>

      <Button variant="ghost" size="sm" onclick={toggleSettings}>
        <Settings class="w-4 h-4" />
      </Button>
    </div>
  </header>

  <!-- Main Content -->
  <main class="flex-1 flex flex-col p-6 gap-6">
    <!-- Log Viewer -->
    <div class="flex-1 relative">
      <LogViewer logs={serviceStore.logs} onclear={handleClearLogs} />
    </div>

    <!-- Controls -->
    <div class="flex items-center justify-center gap-4">
      {#if serviceStore.running}
        <Button variant="danger" onclick={handleStop}>
          <Square class="w-4 h-4" />
          Stop
        </Button>
        <Button variant="secondary" onclick={handleRestart}>
          <RotateCcw class="w-4 h-4" />
          Restart
        </Button>
      {:else}
        <Button onclick={handleStart}>
          <Play class="w-4 h-4" />
          Start Service
        </Button>
      {/if}

      <Button variant="secondary" onclick={toggleSettings}>
        <Settings class="w-4 h-4" />
        Settings
      </Button>
    </div>
  </main>
</div>

<!-- Settings Panel (slide-in) -->
{#if showSettings}
  <div class="fixed inset-0 z-50">
    <!-- Backdrop -->
    <button
      type="button"
      class="absolute inset-0 bg-black/50"
      onclick={toggleSettings}
      onkeydown={(e) => e.key === "Escape" && toggleSettings()}
      aria-label="Close settings"
    ></button>

    <!-- Panel -->
    <div
      class="absolute right-0 top-0 bottom-0 w-80 bg-bg-card border-l border-border p-6 overflow-y-auto"
    >
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-lg font-bold text-text">Settings</h2>
        <button
          type="button"
          class="p-2 hover:bg-bg-input rounded-lg transition-colors"
          onclick={toggleSettings}
        >
          &times;
        </button>
      </div>

      <div class="space-y-6">
        <div>
          <h3 class="text-sm font-medium text-text mb-2">About</h3>
          <p class="text-sm text-text-muted">
            Son of Simon v0.1.0<br />
            AI-powered macOS automation
          </p>
        </div>

        <div>
          <h3 class="text-sm font-medium text-text mb-2">Configuration</h3>
          <p class="text-sm text-text-muted mb-3">
            Edit settings in ~/.macbot/.env
          </p>
          <Button
            variant="secondary"
            size="sm"
            onclick={() => open("~/.macbot/.env")}
          >
            Open Config File
          </Button>
        </div>

        <div>
          <h3 class="text-sm font-medium text-text mb-2">Reset</h3>
          <p class="text-sm text-text-muted mb-3">
            Reset onboarding to reconfigure from scratch.
          </p>
          <Button
            variant="danger"
            size="sm"
            onclick={async () => {
              await onboardingStore.reset();
              window.location.reload();
            }}
          >
            Reset Onboarding
          </Button>
        </div>
      </div>
    </div>
  </div>
{/if}
