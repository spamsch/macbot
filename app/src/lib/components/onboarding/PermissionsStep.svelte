<script lang="ts">
  import { Button } from "$lib/components/ui";
  import { invoke } from "@tauri-apps/api/core";
  import {
    Shield,
    Check,
    X,
    ExternalLink,
    RefreshCw,
    Mail,
    Calendar,
    ListTodo,
    StickyNote,
    Globe,
  } from "lucide-svelte";
  import { onboardingStore, type PermissionsData } from "$lib/stores/onboarding.svelte";

  interface Props {
    onNext: () => void;
    onBack: () => void;
  }

  let { onNext, onBack }: Props = $props();

  let checking = $state(false);

  const apps = [
    { key: "Mail", icon: Mail, name: "Mail" },
    { key: "Calendar", icon: Calendar, name: "Calendar" },
    { key: "Reminders", icon: ListTodo, name: "Reminders" },
    { key: "Notes", icon: StickyNote, name: "Notes" },
    { key: "Safari", icon: Globe, name: "Safari" },
  ];

  // Derive permission state from store
  let permissions = $derived(onboardingStore.state.data.permissions);
  let allGranted = $derived(
    permissions.accessibility &&
      Object.values(permissions.automation).every(Boolean)
  );

  async function openAccessibilitySettings() {
    await invoke("open_system_preferences", {
      pane: "com.apple.preference.security?Privacy_Accessibility",
    });
  }

  async function openAutomationSettings() {
    await invoke("open_system_preferences", {
      pane: "com.apple.preference.security?Privacy_Automation",
    });
  }

  async function checkPermissions() {
    checking = true;
    try {
      // In a real implementation, this would call `son doctor --json`
      // and parse the results. For now, we'll simulate checking.
      // The actual permission check would be done via the sidecar.

      // Simulated delay for UX
      await new Promise((resolve) => setTimeout(resolve, 1000));

      // TODO: Actually check permissions via sidecar
      // const result = await Command.create("son", ["doctor", "--json"]).execute();
      // const doctorOutput = JSON.parse(result.stdout);
      // await onboardingStore.updatePermissions(doctorOutput.permissions);
    } finally {
      checking = false;
    }
  }

  function handleContinue() {
    // Allow continuing even without all permissions (with warning)
    onNext();
  }
</script>

<div class="flex flex-col px-8 py-6">
  <div class="flex items-center gap-3 mb-2">
    <div class="p-2 bg-primary/20 rounded-lg">
      <Shield class="w-6 h-6 text-primary" />
    </div>
    <h2 class="text-2xl font-bold text-text">Grant Permissions</h2>
  </div>

  <p class="text-text-muted mb-6">
    Son of Simon needs permission to control macOS apps. Grant access in System
    Settings.
  </p>

  <!-- Accessibility Permission -->
  <div class="mb-6">
    <div
      class="flex items-center justify-between p-4 bg-bg-card rounded-lg border border-border"
    >
      <div class="flex items-center gap-3">
        <div
          class="w-8 h-8 rounded-full flex items-center justify-center
                 {permissions.accessibility
            ? 'bg-success/20 text-success'
            : 'bg-bg-input text-text-muted'}"
        >
          {#if permissions.accessibility}
            <Check class="w-4 h-4" />
          {:else}
            <X class="w-4 h-4" />
          {/if}
        </div>
        <div>
          <h3 class="font-medium text-text">Accessibility</h3>
          <p class="text-sm text-text-muted">Required for automation</p>
        </div>
      </div>
      <Button variant="secondary" size="sm" onclick={openAccessibilitySettings}>
        Open Settings
        <ExternalLink class="w-4 h-4" />
      </Button>
    </div>
  </div>

  <!-- Automation Permissions -->
  <div class="mb-6">
    <div class="flex items-center justify-between mb-3">
      <h3 class="font-medium text-text">App Automation</h3>
      <Button variant="ghost" size="sm" onclick={openAutomationSettings}>
        Open Settings
        <ExternalLink class="w-4 h-4" />
      </Button>
    </div>

    <div class="grid grid-cols-2 gap-2">
      {#each apps as app}
        <div
          class="flex items-center gap-3 p-3 bg-bg-card rounded-lg border border-border"
        >
          <div
            class="w-6 h-6 rounded flex items-center justify-center
                   {permissions.automation[app.key]
              ? 'bg-success/20 text-success'
              : 'bg-bg-input text-text-muted'}"
          >
            {#if permissions.automation[app.key]}
              <Check class="w-3 h-3" />
            {:else}
              <X class="w-3 h-3" />
            {/if}
          </div>
          <app.icon class="w-4 h-4 text-text-muted" />
          <span class="text-sm text-text">{app.name}</span>
        </div>
      {/each}
    </div>
  </div>

  <!-- Refresh Button -->
  <Button
    variant="secondary"
    onclick={checkPermissions}
    loading={checking}
    disabled={checking}
  >
    <RefreshCw class="w-4 h-4" />
    Check Permissions
  </Button>

  {#if !allGranted}
    <p class="text-sm text-warning mt-4 text-center">
      Some permissions are not granted. You can continue, but some features may
      not work.
    </p>
  {/if}

  <!-- Navigation -->
  <div class="flex justify-between mt-6 pt-6 border-t border-border">
    <Button variant="ghost" onclick={onBack}>Back</Button>
    <Button onclick={handleContinue}>
      {allGranted ? "Continue" : "Continue Anyway"}
    </Button>
  </div>
</div>
