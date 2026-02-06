<script lang="ts">
  import { skillsStore, type Skill } from "$lib/stores/skills.svelte";
  import { Button } from "$lib/components/ui";
  import {
    ArrowLeft,
    Zap,
    Mail,
    Calendar,
    Bell,
    StickyNote,
    Globe,
    Check,
    X,
    AlertTriangle,
    MousePointer2,
    Package,
    Copy,
    Sparkles,
    Loader2,
  } from "lucide-svelte";

  interface Props {
    skill: Skill;
    onback?: () => void;
    onedit?: (skill: Skill) => void;
  }

  let { skill, onback, onedit }: Props = $props();

  function getIcon(skillId: string) {
    const icons: Record<string, typeof Mail> = {
      mail_assistant: Mail,
      calendar_assistant: Calendar,
      reminders_assistant: Bell,
      notes_assistant: StickyNote,
      safari_assistant: Globe,
      browser_automation: MousePointer2,
      clawhub: Package,
    };
    return icons[skillId] || Zap;
  }

  const Icon = $derived(getIcon(skill.id));
  let enriching = $state(false);
  let enrichError = $state<string | null>(null);

  // A skill needs enrichment if it has a source_path (user skill) and no enriched metadata
  const needsEnrichment = $derived(
    skill.source_path && !skill.is_builtin && skill.tasks.length === 0 && skill.examples.length === 0
  );

  async function handleToggle() {
    await skillsStore.toggle(skill.id);
  }

  async function handleEnrich() {
    enriching = true;
    enrichError = null;
    const result = await skillsStore.enrichSkill(skill.id);
    enriching = false;
    if (!result.success) {
      enrichError = result.error || "Enrichment failed";
    }
  }
</script>

<div class="space-y-6">
  <!-- Header -->
  <div class="flex items-center gap-3">
    {#if onback}
      <button
        type="button"
        class="p-2 text-text-muted hover:text-text hover:bg-bg-card rounded-lg transition-colors"
        onclick={onback}
      >
        <ArrowLeft class="w-5 h-5" />
      </button>
    {/if}

    <div
      class="w-12 h-12 rounded-xl flex items-center justify-center {skill.enabled
        ? 'bg-primary/10 text-primary'
        : 'bg-bg-input text-text-muted'}"
    >
      <Icon class="w-6 h-6" />
    </div>

    <div class="flex-1">
      <div class="flex items-center gap-2">
        <h2 class="text-xl font-bold text-text">{skill.name}</h2>
        {#if !skill.is_builtin}
          <span class="text-xs px-2 py-0.5 bg-primary/10 text-primary rounded">custom</span>
        {/if}
      </div>
      <p class="text-sm text-text-muted">{skill.id}</p>
    </div>

    <!-- Toggle -->
    <button
      type="button"
      class="relative w-14 h-8 rounded-full transition-colors {skill.enabled
        ? 'bg-primary'
        : 'bg-bg-input'}"
      onclick={handleToggle}
      aria-label={skill.enabled ? "Disable skill" : "Enable skill"}
    >
      <span
        class="absolute top-1.5 left-1.5 w-5 h-5 bg-white rounded-full transition-transform {skill.enabled
          ? 'translate-x-6'
          : 'translate-x-0'}"
      ></span>
    </button>
  </div>

  <!-- Description -->
  <div class="p-4 bg-bg-card rounded-xl border border-border">
    <p class="text-text">{skill.description}</p>
  </div>

  <!-- Apps & Tasks -->
  {#if skill.apps.length > 0 || skill.tasks.length > 0}
    <div class="grid grid-cols-2 gap-4">
      {#if skill.apps.length > 0}
        <div class="p-4 bg-bg-card rounded-xl border border-border">
          <h3 class="text-sm font-medium text-text-muted mb-2">Apps</h3>
          <div class="flex flex-wrap gap-2">
            {#each skill.apps as app}
              <span class="px-2 py-1 bg-bg-input text-text text-sm rounded-lg">{app}</span>
            {/each}
          </div>
        </div>
      {/if}

      {#if skill.tasks.length > 0}
        <div class="p-4 bg-bg-card rounded-xl border border-border">
          <h3 class="text-sm font-medium text-text-muted mb-2">Tasks</h3>
          <div class="flex flex-wrap gap-2">
            {#each skill.tasks as task}
              <span class="px-2 py-1 bg-bg-input text-text text-sm rounded-lg font-mono">
                {task}
              </span>
            {/each}
          </div>
        </div>
      {/if}
    </div>
  {/if}

  <!-- Examples -->
  {#if skill.examples.length > 0}
    <div class="p-4 bg-bg-card rounded-xl border border-border">
      <h3 class="text-sm font-medium text-text-muted mb-3">Examples</h3>
      <ul class="space-y-2">
        {#each skill.examples as example}
          <li class="flex items-start gap-2 text-text">
            <span class="text-primary mt-0.5">&bull;</span>
            <span class="text-sm">"{example}"</span>
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <!-- Safe Defaults -->
  {#if Object.keys(skill.safe_defaults).length > 0}
    <div class="p-4 bg-bg-card rounded-xl border border-border">
      <h3 class="text-sm font-medium text-text-muted mb-3">
        <Check class="w-4 h-4 inline mr-1" />
        Safe Defaults
      </h3>
      <div class="grid grid-cols-2 gap-2">
        {#each Object.entries(skill.safe_defaults) as [key, value]}
          <div class="flex items-center gap-2">
            <span class="text-sm text-text-muted">{key}:</span>
            <span class="text-sm text-text font-mono">{value}</span>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Confirm Before Write -->
  {#if skill.confirm_before_write.length > 0}
    <div class="p-4 bg-warning/10 rounded-xl border border-warning/30">
      <h3 class="text-sm font-medium text-warning mb-3">
        <AlertTriangle class="w-4 h-4 inline mr-1" />
        Requires Confirmation
      </h3>
      <ul class="space-y-1">
        {#each skill.confirm_before_write as action}
          <li class="text-sm text-text flex items-center gap-2">
            <X class="w-3 h-3 text-warning" />
            {action}
          </li>
        {/each}
      </ul>
    </div>
  {/if}

  <!-- Enrich with AI -->
  {#if needsEnrichment}
    <div class="p-4 bg-primary/5 rounded-xl border border-primary/30">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-sm font-medium text-text mb-1">This skill hasn't been enriched yet</h3>
          <p class="text-xs text-text-muted">Use AI to add task mappings, examples, and behavior notes.</p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onclick={handleEnrich}
          disabled={enriching}
        >
          {#if enriching}
            <Loader2 class="w-4 h-4 animate-spin" />
            Enriching...
          {:else}
            <Sparkles class="w-4 h-4" />
            Enrich with AI
          {/if}
        </Button>
      </div>
      {#if enrichError}
        <p class="mt-2 text-xs text-error">{enrichError}</p>
      {/if}
    </div>
  {/if}

  <!-- Customize -->
  <div class="flex items-center justify-between p-3 bg-bg-card rounded-xl border border-border">
    <div>
      <p class="text-sm text-text">
        {#if skill.is_builtin}
          Create a custom version in ~/.macbot/skills/
        {:else}
          Edit your custom skill
        {/if}
      </p>
    </div>
    <Button variant="secondary" size="sm" onclick={() => onedit?.(skill)}>
      <Copy class="w-4 h-4" />
      Customize
    </Button>
  </div>
</div>
