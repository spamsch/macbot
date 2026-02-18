<script lang="ts">
  import { Button, Input } from "$lib/components/ui";
  import { SkillsList, SkillDetail, SkillEditor } from "$lib/components/skills";
  import ChatPanel from "$lib/components/ChatPanel.svelte";
  import { chatStore } from "$lib/stores/chat.svelte";
  import { onboardingStore } from "$lib/stores/onboarding.svelte";
  import { skillsStore, type Skill } from "$lib/stores/skills.svelte";
  import { memoryStore } from "$lib/stores/memory.svelte";
  import { heartbeatStore } from "$lib/stores/heartbeat.svelte";
  import { routingStore } from "$lib/stores/routing.svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { getVersion } from "@tauri-apps/api/app";
  import { Command } from "@tauri-apps/plugin-shell";
  import { homeDir, join } from "@tauri-apps/api/path";
  import { onMount } from "svelte";
  import {
    Settings,
    Key,
    Bot,
    MessageSquare,
    FolderOpen,
    RefreshCw,
    Zap,
    Brain,
    Heart,
    MessageCircle,
    Shield,
    Check,
    X,
    RotateCcw,
    Save,
    FileText,
    Route,
    ChevronUp,
    ChevronDown,
    Trash2,
    Plus,
  } from "lucide-svelte";

  let showSettings = $state(false);
  let showSkills = $state(false);
  let showMemory = $state(false);
  let showHeartbeat = $state(false);
  let showRouting = $state(false);
  let showChat = $state(false);
  let selectedSkill = $state<Skill | null>(null);
  let editingSkill = $state<Skill | null>(null);
  let config = $state<Record<string, string>>({});
  let loading = $state(true);
  let error = $state<string | null>(null);
  let appVersion = $state("0.0.0");

  onMount(async () => {
    await loadConfig();
    appVersion = await getVersion();
    // Auto-start the service
    chatStore.connect();
  });

  async function loadConfig() {
    loading = true;
    error = null;
    try {
      const content = await invoke<string>("read_config");
      const parsed: Record<string, string> = {};
      for (const line of content.split("\n")) {
        const trimmed = line.trim();
        if (trimmed && !trimmed.startsWith("#")) {
          const eqIndex = trimmed.indexOf("=");
          if (eqIndex > 0) {
            const key = trimmed.substring(0, eqIndex);
            const value = trimmed.substring(eqIndex + 1);
            parsed[key] = value;
          }
        }
      }
      config = parsed;
    } catch (e) {
      error = `Failed to load config: ${e}`;
    } finally {
      loading = false;
    }
  }

  function toggleSettings() {
    showSettings = !showSettings;
  }

  function toggleSkills() {
    showSkills = !showSkills;
    selectedSkill = null;
    editingSkill = null;
  }

  function toggleMemory() {
    showMemory = !showMemory;
    if (showMemory) {
      memoryStore.load();
    }
  }

  function toggleHeartbeat() {
    showHeartbeat = !showHeartbeat;
    if (showHeartbeat) {
      heartbeatStore.load();
    }
  }

  function toggleRouting() {
    showRouting = !showRouting;
    if (showRouting) {
      routingStore.load();
    }
  }

  function toggleChat() {
    showChat = !showChat;
  }

  function handleSkillSelect(skill: Skill) {
    selectedSkill = skill;
    editingSkill = null;
  }

  function handleSkillEdit(skill: Skill) {
    editingSkill = skill;
  }

  function handleSkillBack() {
    if (editingSkill) {
      editingSkill = null;
    } else {
      selectedSkill = null;
    }
  }

  function handleSkillCreate() {
    // Create a new skill template
    const newSkill: Skill = {
      id: "my_new_skill",
      name: "My New Skill",
      description: "Description of what this skill helps with",
      enabled: true,
      is_builtin: false,
      apps: [],
      tasks: [],
      examples: [],
      safe_defaults: {},
      confirm_before_write: [],
      source_path: null,
    };
    editingSkill = newSkill;
    selectedSkill = null;
  }

  function maskApiKey(key: string): string {
    if (!key || key.length < 12) return "***";
    return key.substring(0, 7) + "..." + key.substring(key.length - 4);
  }

  function getModelDisplay(model: string): string {
    if (model.startsWith("pico/")) return `Pico (${model.split("/").pop()})`;
    if (model.startsWith("openrouter/")) {
      // e.g. "openrouter/deepseek/deepseek-v3.2-20251201" -> "OpenRouter (deepseek-v3.2-20251201)"
      const parts = model.split("/");
      return `OpenRouter (${parts[parts.length - 1]})`;
    }
    if (model.includes("gpt") || model.includes("o4-") || model.includes("o3-")) return `OpenAI (${model.split("/").pop()})`;
    if (model.includes("claude")) return `Anthropic (${model.split("/").pop()})`;
    return model;
  }

  async function openConfigFile() {
    const home = await homeDir();
    const configPath = await join(home, ".macbot", ".env");
    const command = Command.create("exec-sh", ["-c", `open "${configPath}"`]);
    await command.execute();
  }

  async function openConfigFolder() {
    const home = await homeDir();
    const folderPath = await join(home, ".macbot");
    const command = Command.create("exec-sh", ["-c", `open "${folderPath}"`]);
    await command.execute();
  }

  function statusColor(state: typeof chatStore.connectionState): string {
    switch (state) {
      case "connected": return "bg-success";
      case "connecting": return "bg-warning animate-pulse";
      case "disconnected": return "bg-text-muted";
      case "error": return "bg-error";
    }
  }

  function statusLabel(state: typeof chatStore.connectionState): string {
    switch (state) {
      case "connected": return "Running";
      case "connecting": return "Starting...";
      case "disconnected": return "Stopped";
      case "error": return "Error";
    }
  }

  function statusTextColor(state: typeof chatStore.connectionState): string {
    switch (state) {
      case "connected": return "text-success";
      case "connecting": return "text-warning";
      case "disconnected": return "text-text-muted";
      case "error": return "text-error";
    }
  }

  // --- Settings panel: AI Provider config ---

  interface ModelOption {
    id: string;
    name: string;
    tag?: string;
  }

  interface ProviderConfig {
    id: string;
    name: string;
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
      ],
    },
    {
      id: "pico",
      name: "Pico (Local)",
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

  // Settings panel state
  let settingsProvider = $state("anthropic");
  let settingsModel = $state("");
  let settingsApiKey = $state("");
  let settingsSaving = $state(false);
  let settingsError = $state<string | null>(null);
  let settingsSuccess = $state<string | null>(null);

  let picoApiBase = $state("http://localhost:11434");
  let picoModels = $state<ModelOption[]>([]);
  let picoLoading = $state(false);

  let paperlessUrl = $state("");
  let paperlessToken = $state("");
  let paperlessSaving = $state(false);
  let paperlessError = $state<string | null>(null);
  let paperlessSuccess = $state<string | null>(null);

  let needsRestart = $state(false);

  const settingsCurrentProvider = $derived(providers.find((p) => p.id === settingsProvider)!);
  const settingsCurrentModels = $derived(
    settingsProvider === "pico" && picoModels.length > 0
      ? picoModels
      : settingsCurrentProvider.models,
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
    if (settingsProvider === "pico") {
      fetchPicoModels(picoApiBase);
    }
  });

  // Set default model when provider changes
  $effect(() => {
    const models = settingsProvider === "pico" && picoModels.length > 0
      ? picoModels
      : settingsCurrentProvider.models;
    if (models.length > 0 && (!settingsModel || !models.some((m) => m.id === settingsModel))) {
      settingsModel = models[0].id;
    }
  });

  // Pre-populate settings from config when panel opens or config reloads
  $effect(() => {
    if (showSettings && config) {
      // Detect provider from existing key or Pico config
      if (config.MACBOT_PICO_API_BASE || (config.MACBOT_MODEL && config.MACBOT_MODEL.startsWith("pico/"))) {
        settingsProvider = "pico";
        picoApiBase = config.MACBOT_PICO_API_BASE ?? "http://localhost:11434";
      } else if (config.MACBOT_ANTHROPIC_API_KEY) {
        settingsProvider = "anthropic";
      } else if (config.MACBOT_OPENAI_API_KEY) {
        settingsProvider = "openai";
      } else if (config.MACBOT_OPENROUTER_API_KEY) {
        settingsProvider = "openrouter";
      }

      // Pre-populate model
      if (config.MACBOT_MODEL) {
        const model = config.MACBOT_MODEL;
        if (model.startsWith("pico/")) {
          // Pico model — set it directly, discovery will validate later
          settingsProvider = "pico";
          settingsModel = model;
        } else {
          // Find which provider owns this model
          for (const p of providers) {
            if (p.models.some((m) => m.id === model)) {
              settingsProvider = p.id;
              settingsModel = model;
              break;
            }
          }
        }
      }

      // Pre-populate Paperless
      paperlessUrl = config.MACBOT_PAPERLESS_URL ?? "";
      paperlessToken = config.MACBOT_PAPERLESS_API_TOKEN ?? "";
    }
  });

  async function updateConfigKeys(updates: Record<string, string>, removeKeys?: string[]) {
    const raw = await invoke<string>("read_config");
    const allRemoveKeys = new Set(removeKeys ?? []);
    for (const key of Object.keys(updates)) {
      allRemoveKeys.add(key);
    }

    const lines = raw.split("\n").filter((line) => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) return true;
      const eqIndex = trimmed.indexOf("=");
      if (eqIndex <= 0) return true;
      const key = trimmed.substring(0, eqIndex);
      return !allRemoveKeys.has(key);
    });

    for (const [key, value] of Object.entries(updates)) {
      if (value) {
        lines.push(`${key}=${value}`);
      }
    }

    await invoke("write_config", { content: lines.join("\n") + "\n" });
    await loadConfig();
  }

  async function saveAiProvider() {
    settingsSaving = true;
    settingsError = null;
    settingsSuccess = null;

    try {
      const updates: Record<string, string> = {};
      const removeKeys: string[] = [
        "MACBOT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY",
        "MACBOT_OPENAI_API_KEY", "OPENAI_API_KEY",
        "MACBOT_OPENROUTER_API_KEY", "OPENROUTER_API_KEY",
        "MACBOT_PICO_API_BASE",
        "MACBOT_MODEL", "MODEL",
      ];

      if (settingsCurrentProvider.isLocal) {
        // Pico: save server URL, no API key
        updates["MACBOT_PICO_API_BASE"] = picoApiBase;
      } else {
        // Only write API key if user entered a new one
        if (settingsApiKey.trim()) {
          updates[settingsCurrentProvider.envPrefixed] = settingsApiKey;
          updates[settingsCurrentProvider.envStandard] = settingsApiKey;
        } else {
          // Keep existing key for the selected provider
          const existingKey = config[settingsCurrentProvider.envPrefixed];
          if (existingKey) {
            updates[settingsCurrentProvider.envPrefixed] = existingKey;
            updates[settingsCurrentProvider.envStandard] = existingKey;
          }
        }
      }

      updates["MACBOT_MODEL"] = settingsModel;

      await updateConfigKeys(updates, removeKeys);

      // Also store API key in macOS Keychain (preferred source)
      if (!settingsCurrentProvider.isLocal && settingsApiKey.trim()) {
        try {
          const providerName = settingsCurrentProvider.value;
          const cmd = Command.create("security", [
            "add-generic-password",
            "-a", `${providerName}_api_key`,
            "-s", "son-of-simon",
            "-w", settingsApiKey.trim(),
            "-U",
          ]);
          await cmd.execute();
        } catch {
          // Keychain save is best-effort; .env write already succeeded
        }
      }

      settingsApiKey = "";
      settingsSuccess = "AI provider settings saved";
      needsRestart = true;
    } catch (e) {
      settingsError = `Failed to save: ${e}`;
    } finally {
      settingsSaving = false;
    }
  }

  async function savePaperless() {
    paperlessSaving = true;
    paperlessError = null;
    paperlessSuccess = null;

    try {
      const updates: Record<string, string> = {};
      if (paperlessUrl.trim()) {
        updates["MACBOT_PAPERLESS_URL"] = paperlessUrl.trim();
      }
      if (paperlessToken.trim()) {
        updates["MACBOT_PAPERLESS_API_TOKEN"] = paperlessToken.trim();
      }

      const removeKeys = ["MACBOT_PAPERLESS_URL", "MACBOT_PAPERLESS_API_TOKEN"];
      await updateConfigKeys(updates, removeKeys);
      paperlessSuccess = "Paperless-ngx settings saved";
      needsRestart = true;
    } catch (e) {
      paperlessError = `Failed to save: ${e}`;
    } finally {
      paperlessSaving = false;
    }
  }
</script>

<div class="min-h-screen flex flex-col bg-bg">
  <!-- Main Content -->
  <main class="flex-1 flex flex-col items-center justify-center p-8 gap-8">
    <!-- Logo -->
    <div class="flex flex-col items-center gap-4">
      <img src="/icon.png" alt="Son of Simon" class="w-32 h-32" />
      <h1 class="text-2xl font-bold text-text">Son of Simon</h1>
      <p class="text-text-muted text-center">AI-powered macOS automation</p>
    </div>

    <!-- Config Summary -->
    <div class="w-full max-w-md space-y-3">
      <h3 class="text-sm font-semibold text-text-muted text-center uppercase tracking-wide">
        Configuration
      </h3>

      {#if loading}
        <div class="text-center text-text-muted">Loading...</div>
      {:else}
        <!-- Model -->
        <div class="flex items-center gap-3 p-3 bg-bg-card rounded-xl border border-border">
          <Bot class="w-5 h-5 text-primary" />
          <div class="flex-1">
            <p class="text-xs text-text-muted">AI Model</p>
            <p class="text-sm font-medium text-text">
              {config.MACBOT_MODEL ? getModelDisplay(config.MACBOT_MODEL) : "Not configured"}
            </p>
          </div>
        </div>

        <!-- API Key / Local Server -->
        <div class="flex items-center gap-3 p-3 bg-bg-card rounded-xl border border-border">
          <Key class="w-5 h-5 text-primary" />
          <div class="flex-1">
            <p class="text-xs text-text-muted">{config.MACBOT_PICO_API_BASE ? "Local Server" : "API Key"}</p>
            <p class="text-sm font-medium text-text font-mono">
              {#if config.MACBOT_PICO_API_BASE}
                {config.MACBOT_PICO_API_BASE}
              {:else if config.MACBOT_OPENAI_API_KEY}
                {maskApiKey(config.MACBOT_OPENAI_API_KEY)}
              {:else if config.MACBOT_ANTHROPIC_API_KEY}
                {maskApiKey(config.MACBOT_ANTHROPIC_API_KEY)}
              {:else if config.MACBOT_OPENROUTER_API_KEY}
                {maskApiKey(config.MACBOT_OPENROUTER_API_KEY)}
              {:else}
                Not configured
              {/if}
            </p>
          </div>
        </div>

        <!-- Telegram -->
        <div class="flex items-center gap-3 p-3 bg-bg-card rounded-xl border border-border">
          <MessageSquare class="w-5 h-5 text-primary" />
          <div class="flex-1">
            <p class="text-xs text-text-muted">Telegram Bot</p>
            <p class="text-sm font-medium text-text">
              {config.MACBOT_TELEGRAM_BOT_TOKEN ? "Configured" : "Not configured"}
            </p>
          </div>
        </div>

        <!-- App Permissions -->
        <div class="flex items-center gap-3 p-3 bg-bg-card rounded-xl border border-border">
          <Shield class="w-5 h-5 text-primary" />
          <div class="flex-1">
            <p class="text-xs text-text-muted">App Permissions</p>
            {#if chatStore.checkingPermissions}
              <p class="text-sm font-medium text-text-muted">Checking...</p>
            {:else if chatStore.permissions}
              {@const perms = chatStore.permissions}
              {@const apps = ["Mail", "Calendar", "Reminders", "Notes", "Safari"] as const}
              {@const denied = apps.filter(a => !perms[a])}
              {#if denied.length === 0}
                <p class="text-sm font-medium text-success">All granted</p>
              {:else}
                <div class="flex flex-wrap gap-1.5 mt-1">
                  {#each apps as app}
                    <span class="inline-flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded-md {perms[app] ? 'bg-success/10 text-success' : 'bg-error/10 text-error'}">
                      {#if perms[app]}
                        <Check class="w-3 h-3" />
                      {:else}
                        <X class="w-3 h-3" />
                      {/if}
                      {app}
                    </span>
                  {/each}
                </div>
              {/if}
            {:else}
              <button
                type="button"
                class="text-sm font-medium text-primary hover:underline"
                onclick={() => chatStore.checkPermissions()}
              >
                Check permissions
              </button>
            {/if}
          </div>
          {#if chatStore.permissions && Object.values(chatStore.permissions).some(v => !v)}
            <button
              type="button"
              class="text-xs text-primary hover:underline shrink-0"
              onclick={() => chatStore.checkPermissions()}
              title="Re-check (triggers macOS permission prompts for missing apps)"
            >
              Re-check
            </button>
          {/if}
        </div>
      {/if}
    </div>

    {#if chatStore.error}
      <div class="p-4 bg-error/10 border border-error/30 rounded-xl text-error text-sm max-w-md">
        {chatStore.error}
      </div>
    {/if}

    {#if error}
      <div class="p-4 bg-error/10 border border-error/30 rounded-xl text-error text-sm max-w-md">
        {error}
      </div>
    {/if}

    <!-- Chat + Status -->
    <div class="flex items-center gap-3">
      <Button variant="primary" size="sm" onclick={toggleChat}>
        <MessageCircle class="w-4 h-4" />
        Chat
      </Button>

      <!-- Status Pill / Reconnect Button -->
      {#if chatStore.connectionState === "error" || chatStore.connectionState === "disconnected"}
        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors
            {chatStore.connectionState === 'error'
              ? 'border-error/30 bg-error/10 text-error hover:bg-error/20'
              : 'border-border bg-bg-card text-text-muted hover:bg-bg-input'}"
          onclick={() => chatStore.reconnect()}
        >
          <RotateCcw class="w-3 h-3" />
          Reconnect
        </button>
      {:else}
        <span
          class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border
            {chatStore.connectionState === 'connected'
              ? 'border-success/30 bg-success/10 text-success'
              : 'border-warning/30 bg-warning/10 text-warning'}"
        >
          <span class="w-1.5 h-1.5 rounded-full {statusColor(chatStore.connectionState)}"></span>
          {statusLabel(chatStore.connectionState)}
        </span>
      {/if}
    </div>

    <!-- Settings actions -->
    <div class="flex items-center gap-2">
      <Button variant="ghost" size="sm" onclick={toggleSkills}>
        <Zap class="w-4 h-4" />
        Skills
      </Button>
      <Button variant="ghost" size="sm" onclick={toggleMemory}>
        <Brain class="w-4 h-4" />
        Memory
      </Button>
      <Button variant="ghost" size="sm" onclick={toggleHeartbeat}>
        <Heart class="w-4 h-4" />
        Heartbeat
      </Button>
      <Button variant="ghost" size="sm" onclick={toggleRouting}>
        <Route class="w-4 h-4" />
        Routing
      </Button>
      <Button variant="ghost" size="sm" onclick={toggleSettings}>
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
      class="absolute right-0 top-0 bottom-0 w-[480px] bg-bg-card border-l border-border p-6 overflow-y-auto"
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

      {#if needsRestart}
        <div class="flex items-center gap-3 p-3 mb-4 bg-warning/10 border border-warning/30 rounded-xl">
          <div class="flex-1">
            <p class="text-sm font-medium text-warning">Restart required</p>
            <p class="text-xs text-text-muted">Settings were saved. Restart the agent to apply changes.</p>
          </div>
          <Button size="sm" onclick={async () => {
            await chatStore.reconnect();
            needsRestart = false;
          }}>
            <RotateCcw class="w-3.5 h-3.5" />
            Restart
          </Button>
        </div>
      {/if}

      <div class="space-y-6">
        <!-- AI Provider Section -->
        <div>
          <h3 class="text-sm font-medium text-text mb-3">AI Provider</h3>

          <!-- Provider selector -->
          <div class="mb-3">
            <label for="settings-provider" class="text-xs text-text-muted mb-1 block">Provider</label>
            <select
              id="settings-provider"
              bind:value={settingsProvider}
              class="w-full p-2.5 bg-bg-input border border-border rounded-xl text-text text-sm
                     focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary"
            >
              {#each providers as p}
                <option value={p.id}>{p.name}</option>
              {/each}
            </select>
          </div>

          <!-- Model dropdown -->
          <div class="mb-3">
            <label for="settings-model" class="text-xs text-text-muted mb-1 block">
              Model{#if picoLoading}<span class="font-normal ml-1">— discovering...</span>{/if}
            </label>
            <select
              id="settings-model"
              bind:value={settingsModel}
              disabled={picoLoading}
              class="w-full p-2.5 bg-bg-input border border-border rounded-xl text-text text-sm
                     focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary
                     disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {#each settingsCurrentModels as m}
                <option value={m.id}>
                  {m.name}{m.tag ? ` — ${m.tag}` : ""}
                </option>
              {/each}
            </select>
          </div>

          {#if settingsCurrentProvider.isLocal}
            <!-- Pico: Server URL input -->
            <div class="mb-3">
              <Input
                type="url"
                label="Server URL"
                placeholder="http://localhost:11434"
                bind:value={picoApiBase}
              />
              <button
                type="button"
                class="mt-1 text-xs text-primary hover:underline"
                onclick={() => fetchPicoModels(picoApiBase)}
                disabled={picoLoading}
              >
                {picoLoading ? "Discovering models..." : "Refresh models from server"}
              </button>
            </div>
          {:else}
            <!-- Current key display -->
            {#if config[settingsCurrentProvider.envPrefixed]}
              <div class="mb-3 flex items-center gap-2 text-xs text-text-muted">
                <Key class="w-3.5 h-3.5" />
                <span>Current key: <span class="font-mono">{maskApiKey(config[settingsCurrentProvider.envPrefixed])}</span></span>
              </div>
            {/if}

            <!-- API key input -->
            <div class="mb-3">
              <Input
                type="password"
                label="New API Key (leave blank to keep current)"
                placeholder={settingsCurrentProvider.keyPrefix + "..."}
                bind:value={settingsApiKey}
              />
            </div>
          {/if}

          {#if settingsError}
            <p class="text-xs text-error mb-2">{settingsError}</p>
          {/if}
          {#if settingsSuccess}
            <p class="text-xs text-success mb-2">{settingsSuccess}</p>
          {/if}

          <Button size="sm" onclick={saveAiProvider} loading={settingsSaving} disabled={settingsSaving}>
            <Save class="w-4 h-4" />
            Save AI Settings
          </Button>
        </div>

        <hr class="border-border" />

        <!-- Paperless-ngx Section -->
        <div>
          <h3 class="text-sm font-medium text-text mb-3">
            <span class="flex items-center gap-2">
              <FileText class="w-4 h-4 text-primary" />
              Paperless-ngx
            </span>
          </h3>
          <p class="text-xs text-text-muted mb-3">
            Connect to your Paperless-ngx instance for document management.
          </p>

          <div class="mb-3">
            <Input
              type="url"
              label="URL"
              placeholder="http://localhost:8000"
              bind:value={paperlessUrl}
            />
          </div>

          <div class="mb-3">
            <Input
              type="password"
              label="API Token"
              placeholder="Token ..."
              bind:value={paperlessToken}
            />
          </div>

          {#if paperlessError}
            <p class="text-xs text-error mb-2">{paperlessError}</p>
          {/if}
          {#if paperlessSuccess}
            <p class="text-xs text-success mb-2">{paperlessSuccess}</p>
          {/if}

          <Button size="sm" onclick={savePaperless} loading={paperlessSaving} disabled={paperlessSaving}>
            <Save class="w-4 h-4" />
            Save Paperless Settings
          </Button>
        </div>

        <hr class="border-border" />

        <!-- About -->
        <div>
          <h3 class="text-sm font-medium text-text mb-2">About</h3>
          <p class="text-sm text-text-muted">
            Son of Simon v{appVersion}<br />
            AI-powered macOS automation
          </p>
        </div>

        <!-- Config file actions -->
        <div>
          <h3 class="text-sm font-medium text-text mb-2">Configuration</h3>
          <p class="text-sm text-text-muted mb-3">Edit settings in ~/.macbot/.env</p>
          <div class="flex gap-2">
            <Button variant="secondary" size="sm" onclick={openConfigFile}>
              Open Config
            </Button>
            <Button variant="ghost" size="sm" onclick={loadConfig}>
              <RefreshCw class="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div>
          <h3 class="text-sm font-medium text-text mb-2">Config Folder</h3>
          <Button variant="secondary" size="sm" onclick={openConfigFolder}>
            <FolderOpen class="w-4 h-4" />
            Open Folder
          </Button>
        </div>

        <!-- Reset -->
        <div>
          <h3 class="text-sm font-medium text-text mb-2">Reset</h3>
          <p class="text-sm text-text-muted mb-3">Reset onboarding to reconfigure.</p>
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

<!-- Skills Panel (slide-in) -->
{#if showSkills}
  <div class="fixed inset-0 z-50">
    <!-- Backdrop -->
    <button
      type="button"
      class="absolute inset-0 bg-black/50"
      onclick={toggleSkills}
      onkeydown={(e) => e.key === "Escape" && toggleSkills()}
      aria-label="Close skills"
    ></button>

    <!-- Panel -->
    <div
      class="absolute right-0 top-0 bottom-0 w-[520px] bg-bg-card border-l border-border overflow-y-auto"
    >
      {#if editingSkill}
        <!-- Skill Editor View -->
        <SkillEditor
          skill={editingSkill}
          onback={handleSkillBack}
          onsave={() => {
            editingSkill = null;
            selectedSkill = null;
          }}
        />
      {:else if selectedSkill}
        <!-- Skill Detail View -->
        <div class="p-6">
          <SkillDetail
            skill={selectedSkill}
            onback={handleSkillBack}
            onedit={handleSkillEdit}
          />
        </div>
      {:else}
        <!-- Skills List View -->
        <div class="p-6">
          <div class="flex items-center justify-between mb-6">
            <h2 class="text-lg font-bold text-text">Skills</h2>
            <button
              type="button"
              class="p-2 hover:bg-bg-input rounded-lg transition-colors"
              onclick={toggleSkills}
            >
              &times;
            </button>
          </div>

          <SkillsList onselect={handleSkillSelect} oncreate={handleSkillCreate} />

          <div class="mt-6 p-4 bg-bg-input/50 rounded-xl space-y-2">
            <p class="text-xs text-text-muted">
              Skills provide guidance for handling specific types of requests.
              Custom skills require <span class="font-mono">id</span>, <span class="font-mono">name</span>, and <span class="font-mono">description</span> fields.
              Saved to <span class="font-mono">~/.macbot/skills/</span>
            </p>
            <p class="text-xs text-text-muted">
              Want more? Ask the agent: <span class="italic">"Search ClawHub for a Slack skill"</span> or
              <span class="italic">"Install https://clawhub.ai/steipete/slack"</span>.
              Browse community skills at <span class="font-mono">clawhub.ai</span>.
            </p>
          </div>
        </div>
      {/if}
    </div>
  </div>
{/if}

<!-- Memory Panel (slide-in) -->
{#if showMemory}
  <div class="fixed inset-0 z-50">
    <!-- Backdrop -->
    <button
      type="button"
      class="absolute inset-0 bg-black/50"
      onclick={toggleMemory}
      onkeydown={(e) => e.key === "Escape" && toggleMemory()}
      aria-label="Close memory"
    ></button>

    <!-- Panel -->
    <div
      class="absolute right-0 top-0 bottom-0 w-[520px] bg-bg-card border-l border-border flex flex-col"
    >
      <div class="flex items-center justify-between p-6 pb-0">
        <h2 class="text-lg font-bold text-text">Memory</h2>
        <button
          type="button"
          class="p-2 hover:bg-bg-input rounded-lg transition-colors"
          onclick={toggleMemory}
        >
          &times;
        </button>
      </div>

      <p class="text-xs text-text-muted px-6 pt-2">
        Edit <span class="font-mono">~/.macbot/memory.yaml</span> — persistent context for the agent.
      </p>

      <div class="flex-1 flex flex-col p-6 gap-4 min-h-0">
        {#if memoryStore.loading}
          <div class="text-center text-text-muted py-8">Loading...</div>
        {:else}
          <textarea
            class="flex-1 w-full bg-bg-input border border-border rounded-xl p-4 text-sm font-mono text-text resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
            value={memoryStore.content}
            oninput={(e) => memoryStore.setContent(e.currentTarget.value)}
            spellcheck={false}
          ></textarea>

          <div class="flex items-center justify-between">
            <div class="text-xs text-text-muted">
              {#if memoryStore.saving}
                Saving...
              {:else if memoryStore.dirty}
                Unsaved changes
              {:else}
                &nbsp;
              {/if}
            </div>
            <Button
              size="sm"
              onclick={() => memoryStore.save()}
              disabled={memoryStore.saving || !memoryStore.dirty}
              loading={memoryStore.saving}
            >
              Save
            </Button>
          </div>

          {#if memoryStore.error}
            <div class="p-3 bg-error/10 border border-error/30 rounded-xl text-error text-xs">
              {memoryStore.error}
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
{/if}

<!-- Heartbeat Panel (slide-in) -->
{#if showHeartbeat}
  <div class="fixed inset-0 z-50">
    <!-- Backdrop -->
    <button
      type="button"
      class="absolute inset-0 bg-black/50"
      onclick={toggleHeartbeat}
      onkeydown={(e) => e.key === "Escape" && toggleHeartbeat()}
      aria-label="Close heartbeat"
    ></button>

    <!-- Panel -->
    <div
      class="absolute right-0 top-0 bottom-0 w-[520px] bg-bg-card border-l border-border flex flex-col"
    >
      <div class="flex items-center justify-between p-6 pb-0">
        <h2 class="text-lg font-bold text-text">Heartbeat</h2>
        <button
          type="button"
          class="p-2 hover:bg-bg-input rounded-lg transition-colors"
          onclick={toggleHeartbeat}
        >
          &times;
        </button>
      </div>

      <p class="text-xs text-text-muted px-6 pt-2">
        Edit <span class="font-mono">~/.macbot/heartbeat.md</span> — this prompt runs every 30 minutes while the service is active.
      </p>

      <div class="flex-1 flex flex-col p-6 gap-4 min-h-0">
        {#if heartbeatStore.loading}
          <div class="text-center text-text-muted py-8">Loading...</div>
        {:else}
          {#if !heartbeatStore.content.trim() && !heartbeatStore.dirty}
            <button
              type="button"
              class="p-3 bg-primary/5 border border-primary/20 rounded-xl text-sm text-primary hover:bg-primary/10 transition-colors text-left"
              onclick={() => heartbeatStore.setContent(`Quick check — only report if something needs my attention, otherwise stay silent.

1. Scan Mail for unread messages from the last 30 minutes. Flag anything urgent or that needs a reply today.
2. Check Calendar for events starting in the next hour. If a meeting is coming up, note the topic and attendees.
3. Check Reminders for items due today that are not yet completed.
4. Look for Mail threads where I was the last sender with no reply in 3+ days — suggest a follow-up if needed.

Be concise. Skip anything that's purely informational with no action required.`)}
            >
              Generate template prompt
            </button>
          {/if}
          <textarea
            class="flex-1 w-full bg-bg-input border border-border rounded-xl p-4 text-sm font-mono text-text resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
            value={heartbeatStore.content}
            oninput={(e) => heartbeatStore.setContent(e.currentTarget.value)}
            spellcheck={false}
          ></textarea>

          <div class="flex items-center justify-between">
            <div class="text-xs text-text-muted">
              {#if heartbeatStore.saving}
                Saving...
              {:else if heartbeatStore.dirty}
                Unsaved changes
              {:else}
                &nbsp;
              {/if}
            </div>
            <Button
              size="sm"
              onclick={() => heartbeatStore.save()}
              disabled={heartbeatStore.saving || !heartbeatStore.dirty}
              loading={heartbeatStore.saving}
            >
              Save
            </Button>
          </div>

          {#if heartbeatStore.error}
            <div class="p-3 bg-error/10 border border-error/30 rounded-xl text-error text-xs">
              {heartbeatStore.error}
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
{/if}

<!-- Routing Panel (slide-in) -->
{#if showRouting}
  <div class="fixed inset-0 z-50">
    <!-- Backdrop -->
    <button
      type="button"
      class="absolute inset-0 bg-black/50"
      onclick={toggleRouting}
      onkeydown={(e) => e.key === "Escape" && toggleRouting()}
      aria-label="Close routing"
    ></button>

    <!-- Panel -->
    <div
      class="absolute right-0 top-0 bottom-0 w-[520px] bg-bg-card border-l border-border flex flex-col"
    >
      <div class="flex items-center justify-between p-6 pb-0">
        <h2 class="text-lg font-bold text-text">Hybrid Routing</h2>
        <button
          type="button"
          class="p-2 hover:bg-bg-input rounded-lg transition-colors"
          onclick={toggleRouting}
        >
          &times;
        </button>
      </div>

      <p class="text-xs text-text-muted px-6 pt-2">
        Route different skills to different models. First matching route wins. No routes = default model for everything.
      </p>

      <div class="flex-1 flex flex-col p-6 gap-4 min-h-0 overflow-y-auto">
        {#if routingStore.loading}
          <div class="text-center text-text-muted py-8">Loading...</div>
        {:else}
          {#if routingStore.routes.length === 0}
            <div class="text-center text-text-muted py-8">
              <p>No routes configured.</p>
              <p class="text-xs mt-2">Add a route to enable per-skill model switching.</p>
            </div>
          {/if}

          {#each routingStore.routes as route, i}
            <div class="p-4 bg-bg-input border border-border rounded-xl space-y-3">
              <div class="flex items-center gap-2">
                <input
                  type="text"
                  class="flex-1 bg-bg border border-border rounded-lg px-3 py-1.5 text-sm text-text focus:outline-none focus:ring-2 focus:ring-primary/50"
                  value={route.name}
                  oninput={(e) => routingStore.updateRoute(i, { name: e.currentTarget.value })}
                  placeholder="Route name"
                />
                <div class="flex items-center gap-1">
                  <button
                    type="button"
                    class="p-1 hover:bg-bg rounded transition-colors text-text-muted"
                    onclick={() => routingStore.moveRoute(i, "up")}
                    disabled={i === 0}
                  >
                    <ChevronUp class="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    class="p-1 hover:bg-bg rounded transition-colors text-text-muted"
                    onclick={() => routingStore.moveRoute(i, "down")}
                    disabled={i === routingStore.routes.length - 1}
                  >
                    <ChevronDown class="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    class="p-1 hover:bg-error/10 rounded transition-colors text-error/60 hover:text-error"
                    onclick={() => routingStore.removeRoute(i)}
                  >
                    <Trash2 class="w-4 h-4" />
                  </button>
                </div>
              </div>

              <div>
                <label class="text-xs text-text-muted block mb-1">Skills (comma-separated IDs)</label>
                <input
                  type="text"
                  class="w-full bg-bg border border-border rounded-lg px-3 py-1.5 text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
                  value={route.skills.join(", ")}
                  oninput={(e) => routingStore.updateRoute(i, {
                    skills: e.currentTarget.value.split(",").map((s) => s.trim()).filter(Boolean)
                  })}
                  placeholder="mail_assistant, calendar_assistant"
                />
              </div>

              <div>
                <label class="text-xs text-text-muted block mb-1">Model</label>
                <input
                  type="text"
                  class="w-full bg-bg border border-border rounded-lg px-3 py-1.5 text-sm text-text font-mono focus:outline-none focus:ring-2 focus:ring-primary/50"
                  value={route.model}
                  oninput={(e) => routingStore.updateRoute(i, { model: e.currentTarget.value })}
                  placeholder="pico/llama3.2 or anthropic/claude-sonnet-4-5"
                />
              </div>
            </div>
          {/each}

          <button
            type="button"
            class="flex items-center justify-center gap-2 p-3 border border-dashed border-border rounded-xl text-sm text-text-muted hover:text-text hover:border-primary/50 transition-colors"
            onclick={() => routingStore.addRoute()}
          >
            <Plus class="w-4 h-4" />
            Add Route
          </button>

          <div class="flex items-center justify-between pt-2">
            <div class="text-xs text-text-muted">
              {#if routingStore.saving}
                Saving...
              {:else if routingStore.dirty}
                Unsaved changes
              {:else}
                &nbsp;
              {/if}
            </div>
            <Button
              size="sm"
              onclick={() => routingStore.save()}
              disabled={routingStore.saving || !routingStore.dirty}
              loading={routingStore.saving}
            >
              Save
            </Button>
          </div>

          {#if routingStore.error}
            <div class="p-3 bg-error/10 border border-error/30 rounded-xl text-error text-xs">
              {routingStore.error}
            </div>
          {/if}
        {/if}
      </div>
    </div>
  </div>
{/if}

<!-- Chat Panel -->
<ChatPanel visible={showChat} onclose={toggleChat} />
