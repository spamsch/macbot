<script lang="ts">
  import { skillsStore, type Skill } from "$lib/stores/skills.svelte";
  import { onMount } from "svelte";
  import {
    Zap,
    Mail,
    Calendar,
    Bell,
    StickyNote,
    Globe,
    ChevronRight,
    RefreshCw,
    MousePointer2,
    Plus,
  } from "lucide-svelte";

  interface Props {
    onselect?: (skill: Skill) => void;
    oncreate?: () => void;
  }

  let { onselect, oncreate }: Props = $props();

  onMount(() => {
    skillsStore.load();
  });

  function getIcon(skillId: string) {
    const icons: Record<string, typeof Mail> = {
      mail_assistant: Mail,
      calendar_assistant: Calendar,
      reminders_assistant: Bell,
      notes_assistant: StickyNote,
      safari_assistant: Globe,
      browser_automation: MousePointer2,
    };
    return icons[skillId] || Zap;
  }

  async function handleToggle(e: Event, skill: Skill) {
    e.stopPropagation();
    await skillsStore.toggle(skill.id);
  }
</script>

<div class="space-y-4">
  <div class="flex items-center justify-between">
    <div>
      <h3 class="text-lg font-semibold text-text">Skills</h3>
      <p class="text-sm text-text-muted">
        {skillsStore.enabledCount} of {skillsStore.totalCount} enabled
      </p>
    </div>
    <button
      type="button"
      class="p-2 text-text-muted hover:text-text hover:bg-bg-card rounded-lg transition-colors"
      onclick={() => skillsStore.load()}
      disabled={skillsStore.loading}
    >
      <RefreshCw class="w-4 h-4 {skillsStore.loading ? 'animate-spin' : ''}" />
    </button>
  </div>

  <!-- Create New Skill Button -->
  <button
    type="button"
    class="w-full flex items-center gap-3 p-3 bg-primary/5 border border-dashed border-primary/30 rounded-xl hover:bg-primary/10 transition-colors"
    onclick={() => oncreate?.()}
  >
    <div class="w-10 h-10 rounded-lg flex items-center justify-center bg-primary/10 text-primary">
      <Plus class="w-5 h-5" />
    </div>
    <div class="flex-1 text-left">
      <span class="font-medium text-primary">Create New Skill</span>
      <p class="text-sm text-text-muted">Add custom guidance for the agent</p>
    </div>
  </button>

  {#if skillsStore.error}
    <div class="p-3 bg-error/10 border border-error/30 rounded-lg text-error text-sm">
      {skillsStore.error}
    </div>
  {/if}

  {#if skillsStore.loading && skillsStore.skills.length === 0}
    <div class="text-center py-8 text-text-muted">Loading skills...</div>
  {:else if skillsStore.skills.length === 0}
    <div class="text-center py-8 text-text-muted">No skills found</div>
  {:else}
    <div class="space-y-2">
      {#each skillsStore.skills as skill}
        {@const Icon = getIcon(skill.id)}
        <div
          class="w-full flex items-center gap-3 p-3 bg-bg-card rounded-xl border border-border hover:border-primary/50 transition-colors"
        >
          <!-- Clickable area for skill details -->
          <button
            type="button"
            class="flex items-center gap-3 flex-1 min-w-0 text-left"
            onclick={() => onselect?.(skill)}
          >
            <div
              class="w-10 h-10 rounded-lg flex items-center justify-center shrink-0 {skill.enabled
                ? 'bg-primary/10 text-primary'
                : 'bg-bg-input text-text-muted'}"
            >
              <Icon class="w-5 h-5" />
            </div>

            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-medium text-text truncate">{skill.name}</span>
                {#if !skill.is_builtin}
                  <span class="text-xs px-1.5 py-0.5 bg-primary/10 text-primary rounded">
                    custom
                  </span>
                {/if}
              </div>
              <p class="text-sm text-text-muted truncate">{skill.description}</p>
            </div>

            <ChevronRight class="w-5 h-5 text-text-muted shrink-0" />
          </button>

          <!-- Toggle Switch (separate from the detail button) -->
          <button
            type="button"
            class="relative w-11 h-6 rounded-full transition-colors shrink-0 {skill.enabled
              ? 'bg-primary'
              : 'bg-bg-input'}"
            onclick={(e) => handleToggle(e, skill)}
            aria-label={skill.enabled ? "Disable skill" : "Enable skill"}
          >
            <span
              class="absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform {skill.enabled
                ? 'translate-x-5'
                : 'translate-x-0'}"
            ></span>
          </button>
        </div>
      {/each}
    </div>
  {/if}
</div>
