<script lang="ts">
  import { Button } from "$lib/components/ui";
  import { SkillsList, SkillDetail, SkillEditor } from "$lib/components/skills";
  import { serviceStore } from "$lib/stores/service.svelte";
  import { onboardingStore } from "$lib/stores/onboarding.svelte";
  import { skillsStore, type Skill } from "$lib/stores/skills.svelte";
  import { memoryStore } from "$lib/stores/memory.svelte";
  import { heartbeatStore } from "$lib/stores/heartbeat.svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { getVersion } from "@tauri-apps/api/app";
  import { Command } from "@tauri-apps/plugin-shell";
  import { homeDir, join } from "@tauri-apps/api/path";
  import { onMount } from "svelte";
  import {
    Play,
    Square,
    Settings,
    Key,
    Bot,
    MessageSquare,
    FolderOpen,
    RefreshCw,
    Info,
    Terminal,
    ExternalLink,
    Zap,
    Brain,
    Heart,
    Stethoscope,
  } from "lucide-svelte";

  let showSettings = $state(false);
  let showSkills = $state(false);
  let showMemory = $state(false);
  let showHeartbeat = $state(false);
  let selectedSkill = $state<Skill | null>(null);
  let editingSkill = $state<Skill | null>(null);
  let config = $state<Record<string, string>>({});
  let loading = $state(true);
  let starting = $state(false);
  let stopping = $state(false);
  let error = $state<string | null>(null);
  let verbose = $state(false);
  let runningDoctor = $state(false);
  let appVersion = $state("0.0.0");

  onMount(async () => {
    await loadConfig();
    appVersion = await getVersion();
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

  async function handleStart() {
    starting = true;
    error = null;
    try {
      await serviceStore.start(verbose);
    } catch (e) {
      error = `Failed to start: ${e}`;
    } finally {
      starting = false;
    }
  }

  async function handleStop() {
    stopping = true;
    error = null;
    try {
      await serviceStore.stop();
    } catch (e) {
      error = `Failed to stop: ${e}`;
    } finally {
      stopping = false;
    }
  }

  async function handleDoctor() {
    runningDoctor = true;
    error = null;
    try {
      await serviceStore.runDoctor();
    } catch (e) {
      error = `Failed to run doctor: ${e}`;
    } finally {
      runningDoctor = false;
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
    if (model.startsWith("openrouter/")) {
      // e.g. "openrouter/deepseek/deepseek-v3.2-20251201" → "OpenRouter (deepseek-v3.2-20251201)"
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

        <!-- API Key -->
        <div class="flex items-center gap-3 p-3 bg-bg-card rounded-xl border border-border">
          <Key class="w-5 h-5 text-primary" />
          <div class="flex-1">
            <p class="text-xs text-text-muted">API Key</p>
            <p class="text-sm font-medium text-text font-mono">
              {#if config.MACBOT_OPENAI_API_KEY}
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
      {/if}
    </div>

    <!-- Status and Controls -->
    <div class="flex flex-col items-center gap-4">
      <!-- Status Indicator -->
      <div class="flex items-center gap-2">
        <div
          class="w-3 h-3 rounded-full {serviceStore.running ? 'bg-success animate-pulse' : 'bg-text-muted'}"
        ></div>
        <span class="text-sm font-medium {serviceStore.running ? 'text-success' : 'text-text-muted'}">
          {serviceStore.running ? "Running" : "Stopped"}
        </span>
      </div>

      <!-- Action Buttons -->
      {#if serviceStore.running}
        <!-- Running info -->
        <div class="flex flex-col items-center gap-4 p-4 bg-bg-card rounded-xl border border-border max-w-md">
          <p class="text-sm text-text-muted text-center">
            Son of Simon is running! You can now:
          </p>
          <ul class="text-sm text-text-muted space-y-1">
            <li class="flex items-center gap-2">
              <Terminal class="w-4 h-4 text-primary" />
              Type commands in the Terminal window
            </li>
            {#if config.MACBOT_TELEGRAM_BOT_TOKEN}
              <li class="flex items-center gap-2">
                <MessageSquare class="w-4 h-4 text-primary" />
                Send messages to your Telegram bot
              </li>
            {/if}
          </ul>

          <div class="w-full border-t border-border pt-3">
            <p class="text-xs text-text-muted mb-2 font-medium">Try saying:</p>
            <div class="flex flex-wrap gap-2">
              <span class="text-xs bg-bg-input px-2 py-1 rounded-lg text-text-muted">"Check my emails"</span>
              <span class="text-xs bg-bg-input px-2 py-1 rounded-lg text-text-muted">"What's on my calendar?"</span>
              <span class="text-xs bg-bg-input px-2 py-1 rounded-lg text-text-muted">"Remind me to call mom at 5pm"</span>
              <span class="text-xs bg-bg-input px-2 py-1 rounded-lg text-text-muted">"Search the web for..."</span>
            </div>
          </div>
        </div>

        <div class="flex gap-3">
          <Button variant="secondary" onclick={() => serviceStore.showTerminal()}>
            <ExternalLink class="w-4 h-4" />
            Show Terminal
          </Button>
          <Button variant="danger" onclick={handleStop} loading={stopping} disabled={stopping}>
            <Square class="w-4 h-4" />
            Stop
          </Button>
        </div>
      {:else}
        <div class="flex gap-3">
          <Button onclick={handleStart} loading={starting} disabled={starting} size="lg">
            <Play class="w-5 h-5" />
            Start Now
          </Button>
          <Button variant="secondary" onclick={handleDoctor} loading={runningDoctor} disabled={runningDoctor} size="lg">
            <Stethoscope class="w-5 h-5" />
            Doctor
          </Button>
        </div>

        <!-- Verbose Checkbox -->
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            bind:checked={verbose}
            class="w-4 h-4 rounded border-border text-primary focus:ring-primary"
          />
          <span class="text-sm text-text-muted">Verbose logging</span>
        </label>
      {/if}

      <!-- Permission Note -->
      {#if !serviceStore.running}
        <div class="flex items-start gap-2 p-4 bg-bg-card rounded-xl border border-border max-w-md mt-2">
          <Info class="w-5 h-5 text-primary shrink-0 mt-0.5" />
          <p class="text-sm text-text-muted">
            After starting, macOS will ask for permission to access Calendar, Mail, Reminders, and
            other apps. Please allow access for full functionality.
          </p>
        </div>
      {/if}
    </div>

    {#if error}
      <div class="p-4 bg-error/10 border border-error/30 rounded-xl text-error text-sm max-w-md">
        {error}
      </div>
    {/if}

    <!-- Action Buttons -->
    <div class="flex gap-3">
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
            Son of Simon v{appVersion}<br />
            AI-powered macOS automation
          </p>
        </div>

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
