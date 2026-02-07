<script lang="ts">
  import { onMount } from "svelte";
  import { Card, StepIndicator } from "$lib/components/ui";
  import {
    WelcomeStep,
    PermissionsStep,
    ApiKeyStep,
    TelegramStep,
    CompleteStep,
  } from "$lib/components/onboarding";
  import Dashboard from "./Dashboard.svelte";
  import {
    onboardingStore,
    STEPS,
    STEP_LABELS,
    type Step,
  } from "$lib/stores/onboarding.svelte";
  let showDashboard = $state(false);
  let currentStep = $derived(onboardingStore.state.current_step as Step);
  let currentStepIndex = $derived(STEPS.indexOf(currentStep));

  onMount(async () => {
    await onboardingStore.load();
    if (onboardingStore.state.completed) {
      showDashboard = true;
    }
  });

  async function nextStep() {
    await onboardingStore.nextStep();
  }

  async function prevStep() {
    await onboardingStore.prevStep();
  }

  function launchDashboard() {
    showDashboard = true;
  }
</script>

{#if onboardingStore.loading}
  <div class="min-h-screen flex items-center justify-center">
    <div class="text-slate-400 text-lg">Loading...</div>
  </div>
{:else if showDashboard}
  <Dashboard />
{:else}
  <div class="min-h-screen flex flex-col items-center justify-center p-6">
    <Card padding="none">
      <div class="w-[680px] max-w-full">
        <!-- Header with logo -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-border">
          <div class="flex items-center gap-3">
            <img src="/logo.svg" alt="Son of Simon" class="w-8 h-8" />
            <span class="font-semibold text-text">Son of Simon</span>
          </div>
          {#if currentStep !== "welcome" && currentStep !== "complete"}
            <span class="text-sm text-text-muted">Setup Assistant</span>
          {/if}
        </div>

        <!-- Step Indicator (not shown on welcome) -->
        {#if currentStep !== "welcome"}
          <div class="px-6 pt-4">
            <StepIndicator
              steps={STEPS.slice(1).map((s) => STEP_LABELS[s])}
              currentStep={currentStepIndex - 1}
            />
          </div>
        {/if}

        <!-- Step Content -->
        <div>
          {#if currentStep === "welcome"}
            <WelcomeStep onNext={nextStep} />
          {:else if currentStep === "permissions"}
            <PermissionsStep onNext={nextStep} onBack={prevStep} />
          {:else if currentStep === "apikey"}
            <ApiKeyStep onNext={nextStep} onBack={prevStep} />
          {:else if currentStep === "telegram"}
            <TelegramStep onNext={nextStep} onBack={prevStep} />
          {:else if currentStep === "complete"}
            <CompleteStep onLaunch={launchDashboard} />
          {/if}
        </div>
      </div>
    </Card>
  </div>
{/if}
