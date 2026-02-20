<script lang="ts">
  import { onMount } from "svelte";
  import { Button } from "$lib/components/ui";
  import { invoke } from "@tauri-apps/api/core";
  import {
    Shield,
    Check,
    Circle,
    ExternalLink,
    ArrowRight,
    ArrowLeft,
    Info,
    CheckCircle,
    FolderOpen,
    X,
  } from "lucide-svelte";
  import { onboardingStore, type PermissionsData } from "$lib/stores/onboarding.svelte";

  interface Props {
    onNext: () => void;
    onBack: () => void;
  }

  let { onNext, onBack }: Props = $props();

  // Derive permission state from store
  let permissions = $derived(onboardingStore.state.data.permissions);

  let accessibilityGranted = $state(false);
  let checking = $state(true);
  let folderAccess = $state<Record<string, boolean>>({ Documents: false, Downloads: false, Desktop: false });
  let checkingFolders = $state(false);

  async function checkFolderAccess() {
    checkingFolders = true;
    try {
      const result = await invoke<Record<string, boolean>>("check_folder_access");
      folderAccess = result;
      await onboardingStore.updatePermissions({ folder_access: result });
    } catch (e) {
      console.error("Failed to check folder access:", e);
    }
    checkingFolders = false;
  }

  onMount(async () => {
    // Check if accessibility is already granted
    try {
      const hasAccess = await invoke<boolean>("check_accessibility_permission");
      accessibilityGranted = hasAccess;
      if (hasAccess) {
        await onboardingStore.updatePermissions({ accessibility: true });
      }
    } catch (e) {
      console.error("Failed to check accessibility:", e);
    }
    checking = false;

    // Check folder access
    await checkFolderAccess();
  });

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

  async function openFilesAndFoldersSettings() {
    await invoke("open_system_preferences", {
      pane: "com.apple.preference.security?Privacy_FilesAndFolders",
    });
  }

  async function recheckAccessibility() {
    checking = true;
    try {
      const hasAccess = await invoke<boolean>("check_accessibility_permission");
      accessibilityGranted = hasAccess;
      if (hasAccess) {
        await onboardingStore.updatePermissions({ accessibility: true });
      }
    } catch (e) {
      console.error("Failed to check accessibility:", e);
    }
    checking = false;
  }

  function handleContinue() {
    onNext();
  }
</script>

<div class="flex flex-col px-10 py-8">
  <div class="flex items-center gap-3 mb-3">
    <div class="p-2 bg-primary/10 rounded-lg">
      <Shield class="w-6 h-6 text-primary" />
    </div>
    <h2 class="text-2xl font-bold text-text">Allow Access to Your Mac</h2>
  </div>

  <p class="text-text-muted mb-8">
    For Son of Simon to help you, macOS needs your permission. This keeps you in control
    of what the app can do.
  </p>

  <!-- Step 1: Accessibility -->
  <div class="mb-6">
    {#if accessibilityGranted}
      <!-- Already granted -->
      <div class="flex items-start gap-4 p-5 bg-success/10 rounded-xl border border-success/30">
        <div class="w-8 h-8 rounded-full bg-success text-white flex items-center justify-center shrink-0">
          <Check class="w-5 h-5" />
        </div>
        <div class="flex-1">
          <h3 class="font-semibold text-text mb-2">Accessibility Access Enabled</h3>
          <p class="text-sm text-text-muted">
            Great! Son of Simon already has permission to interact with other apps on your Mac.
          </p>
        </div>
      </div>
    {:else}
      <!-- Not granted yet -->
      <div class="flex items-start gap-4 p-5 bg-bg-card rounded-xl border border-border">
        <div class="w-8 h-8 rounded-full bg-primary text-white flex items-center justify-center font-bold shrink-0">
          1
        </div>
        <div class="flex-1">
          <h3 class="font-semibold text-text mb-2">Enable Accessibility Access</h3>
          <p class="text-sm text-text-muted mb-4">
            This allows Son of Simon to interact with other apps on your Mac. When System Settings opens:
          </p>
          <ol class="text-sm text-text-muted space-y-2 mb-4 ml-4">
            <li class="flex gap-2">
              <span class="text-primary font-medium">1.</span>
              <span>Click the <strong class="text-text">+</strong> button at the bottom of the list</span>
            </li>
            <li class="flex gap-2">
              <span class="text-primary font-medium">2.</span>
              <span>Find and select <strong class="text-text">Son of Simon</strong> in your Applications folder</span>
            </li>
            <li class="flex gap-2">
              <span class="text-primary font-medium">3.</span>
              <span>Make sure the toggle next to it is turned <strong class="text-text">on</strong></span>
            </li>
          </ol>
          <div class="flex gap-3">
            <Button onclick={openAccessibilitySettings}>
              Open Accessibility Settings
              <ExternalLink class="w-4 h-4" />
            </Button>
            <Button variant="secondary" onclick={recheckAccessibility} loading={checking}>
              {checking ? "Checking..." : "I've Done This"}
            </Button>
          </div>
        </div>
      </div>
    {/if}
  </div>

  <!-- Step 2: Automation (Optional) -->
  <div class="mb-6">
    <div class="flex items-start gap-4 p-5 bg-bg-card rounded-xl border border-border">
      <div class="w-8 h-8 rounded-full bg-primary text-white flex items-center justify-center font-bold shrink-0">
        2
      </div>
      <div class="flex-1">
        <div class="flex items-center gap-2 mb-2">
          <h3 class="font-semibold text-text">Allow App Automation</h3>
          <span class="text-xs bg-bg-card border border-border px-2 py-0.5 rounded text-text-muted">
            Will appear after first use
          </span>
        </div>
        <p class="text-sm text-text-muted mb-4">
          The first time Son of Simon tries to control an app (like Mail, Calendar, or Things3),
          macOS will ask for your permission. Just click <strong class="text-text">"OK"</strong> when prompted.
        </p>
        <div class="flex items-start gap-2 p-3 bg-primary/5 rounded-lg border border-primary/20">
          <Info class="w-4 h-4 text-primary shrink-0 mt-0.5" />
          <p class="text-xs text-text-muted">
            You can also manage these permissions later in System Settings → Privacy & Security → Automation
          </p>
        </div>
      </div>
    </div>
  </div>

  <!-- Step 3: Files & Folders Access -->
  <div class="mb-6">
    <div class="flex items-start gap-4 p-5 bg-bg-card rounded-xl border border-border">
      <div class="w-8 h-8 rounded-full bg-primary text-white flex items-center justify-center font-bold shrink-0">
        3
      </div>
      <div class="flex-1">
        <h3 class="font-semibold text-text mb-2">Files & Folders Access</h3>
        <p class="text-sm text-text-muted mb-4">
          Son of Simon needs access to common folders for downloading attachments, searching files, and managing documents.
        </p>

        <!-- Per-folder status -->
        <div class="space-y-2 mb-4">
          {#each Object.entries(folderAccess) as [folder, accessible]}
            <div class="flex items-center gap-2">
              {#if accessible}
                <Check class="w-4 h-4 text-success" />
              {:else}
                <X class="w-4 h-4 text-error" />
              {/if}
              <span class="text-sm" class:text-text={accessible} class:text-text-muted={!accessible}>
                ~/{folder}
              </span>
            </div>
          {/each}
        </div>

        <div class="flex gap-3">
          <Button onclick={openFilesAndFoldersSettings}>
            Open Files & Folders Settings
            <ExternalLink class="w-4 h-4" />
          </Button>
          <Button variant="secondary" onclick={checkFolderAccess} loading={checkingFolders}>
            {checkingFolders ? "Checking..." : "Recheck"}
          </Button>
        </div>
      </div>
    </div>
  </div>

  <!-- Info box -->
  <div class="flex items-start gap-3 p-4 bg-bg-card rounded-xl border border-border mb-6">
    <Info class="w-5 h-5 text-primary shrink-0 mt-0.5" />
    <div>
      <p class="text-sm text-text-muted">
        <strong class="text-text">Why is this needed?</strong> macOS protects your privacy by requiring
        apps to ask before they can control other apps. Son of Simon needs this to read your emails,
        create calendar events, and perform other tasks on your behalf.
      </p>
    </div>
  </div>

  <!-- Navigation -->
  <div class="flex justify-between pt-6 border-t border-border">
    <Button variant="ghost" onclick={onBack}>
      <ArrowLeft class="w-4 h-4" />
      Back
    </Button>
    <Button onclick={handleContinue}>
      Continue
      <ArrowRight class="w-4 h-4" />
    </Button>
  </div>
</div>
