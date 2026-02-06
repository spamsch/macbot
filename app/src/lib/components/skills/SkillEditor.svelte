<script lang="ts">
  import { skillsStore, type Skill } from "$lib/stores/skills.svelte";
  import { Button } from "$lib/components/ui";
  import { ArrowLeft, Save, AlertCircle, Sparkles, Loader2 } from "lucide-svelte";
  import { onMount } from "svelte";

  interface Props {
    skill: Skill;
    onback?: () => void;
    onsave?: () => void;
  }

  let { skill, onback, onsave }: Props = $props();

  let content = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let enriching = $state(false);
  let error = $state<string | null>(null);
  let modified = $state(false);

  // Determine if this is creating a new skill (not customizing an existing one)
  const isNewSkill = $derived(!skill.source_path && !skill.is_builtin);

  onMount(async () => {
    await loadContent();
  });

  async function loadContent() {
    loading = true;
    error = null;

    try {
      const result = await skillsStore.readSkillContent(skill.id);
      if (result) {
        content = result;
      } else {
        // Create template for new/missing skill
        content = createTemplate(skill);
      }
    } catch (e) {
      error = `Failed to load skill content: ${e}`;
    } finally {
      loading = false;
    }
  }

  function createTemplate(skill: Skill): string {
    if (isNewSkill) {
      return `---
# REQUIRED fields - the skill won't load without these:
id: my_custom_skill
name: My Custom Skill
description: Describe what this skill helps the agent do

# Optional: List apps this skill relates to
apps: []

# Optional: List task names from 'son tasks' this skill uses
tasks: []

# Examples of prompts that should trigger this skill
examples:
  - "Example prompt that triggers this skill"
  - "Another example prompt"

# Default values the agent should use
safe_defaults: {}

# Actions that require user confirmation before executing
confirm_before_write: []
---

## Behavior Notes

Add guidance here for how the agent should handle requests related to this skill.
This is included in the agent's system prompt when this skill is enabled.

### Example Patterns
- When the user asks about X, first check Y
- Always prefer Z approach over W
`;
    }
    return `---
id: ${skill.id}
name: ${skill.name}
description: ${skill.description}
apps:
${skill.apps.map((a) => `  - ${a}`).join("\n") || "  # No apps specified"}
tasks:
${skill.tasks.map((t) => `  - ${t}`).join("\n") || "  # No tasks specified"}
examples:
${skill.examples.map((e) => `  - "${e}"`).join("\n") || '  - "Example prompt"'}
safe_defaults:
${Object.entries(skill.safe_defaults).map(([k, v]) => `  ${k}: ${JSON.stringify(v)}`).join("\n") || "  # No defaults"}
confirm_before_write:
${skill.confirm_before_write.map((a) => `  - ${a}`).join("\n") || "  # No confirmations required"}
---

${skill.body || "## Behavior Notes\n\nAdd behavior guidance here."}
`;
  }

  function handleChange(e: Event) {
    const target = e.target as HTMLTextAreaElement;
    content = target.value;
    modified = true;
  }

  async function handleSave() {
    saving = true;
    error = null;

    try {
      const result = await skillsStore.writeSkillContent(skill.id, content);
      if (result.success) {
        modified = false;
        onsave?.();
      } else {
        error = result.error || "Failed to save skill";
      }
    } catch (e) {
      error = `Failed to save: ${e}`;
    } finally {
      saving = false;
    }
  }

  async function handleEnrich() {
    // Save first if modified, so enrichment runs on the latest content
    if (modified) {
      await handleSave();
      if (error) return;
    }

    enriching = true;
    error = null;

    try {
      const result = await skillsStore.enrichSkill(skill.id);
      if (result.success) {
        // Reload the editor content with enriched version
        await loadContent();
        modified = false;
      } else {
        error = result.error || "Enrichment failed";
      }
    } catch (e) {
      error = `Failed to enrich: ${e}`;
    } finally {
      enriching = false;
    }
  }
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="flex items-center justify-between p-4 border-b border-border">
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

      <div>
        <h2 class="text-lg font-bold text-text">
          {isNewSkill ? "Create New Skill" : `Customize: ${skill.name}`}
        </h2>
        <p class="text-sm text-text-muted">
          {#if isNewSkill}
            Will be saved to ~/.macbot/skills/
          {:else if skill.is_builtin}
            Creating custom version in ~/.macbot/skills/
          {:else}
            Editing ~/.macbot/skills/{skill.id}
          {/if}
        </p>
      </div>
    </div>

    <div class="flex items-center gap-2">
      {#if modified}
        <span class="text-xs text-warning">Unsaved changes</span>
      {/if}
      {#if !isNewSkill}
        <Button variant="secondary" onclick={handleEnrich} disabled={enriching || saving}>
          {#if enriching}
            <Loader2 class="w-4 h-4 animate-spin" />
            Enriching...
          {:else}
            <Sparkles class="w-4 h-4" />
            Enrich with AI
          {/if}
        </Button>
      {/if}
      <Button onclick={handleSave} loading={saving} disabled={saving || !modified}>
        <Save class="w-4 h-4" />
        Save
      </Button>
    </div>
  </div>

  <!-- Editor -->
  <div class="flex-1 p-4 overflow-hidden">
    {#if error}
      <div
        class="mb-4 p-3 bg-error/10 border border-error/30 rounded-lg text-error text-sm flex items-center gap-2"
      >
        <AlertCircle class="w-4 h-4" />
        {error}
      </div>
    {/if}

    {#if loading}
      <div class="flex items-center justify-center h-full text-text-muted">Loading...</div>
    {:else}
      <div class="h-full flex flex-col">
        <label for="skill-editor" class="text-sm text-text-muted mb-2">SKILL.md Content (YAML frontmatter + Markdown)</label>
        <textarea
          id="skill-editor"
          class="flex-1 w-full p-4 bg-bg-card border border-border rounded-xl text-text font-mono text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          value={content}
          oninput={handleChange}
          spellcheck="false"
        ></textarea>
      </div>
    {/if}
  </div>

  <!-- Help -->
  <div class="p-4 border-t border-border bg-bg-card/50">
    <p class="text-xs text-text-muted">
      <strong>Required fields:</strong> <span class="font-mono">id</span>, <span class="font-mono">name</span>, <span class="font-mono">description</span>.
      {#if isNewSkill}
        The <span class="font-mono">id</span> determines the folder name — use lowercase with underscores (e.g., <span class="font-mono">my_skill</span>).
      {:else}
        Saved to <span class="font-mono">~/.macbot/skills/{skill.id}/SKILL.md</span>.
      {/if}
    </p>
  </div>
</div>
