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
  } from "$lib/stores/onboarding";
  import { serviceStore } from "$lib/stores/service";

  let showDashboard = $state(false);
  let currentStep = $derived(onboardingStore.state.current_step as Step);
  let currentStepIndex = $derived(STEPS.indexOf(currentStep));

  onMount(async () => {
    await onboardingStore.load();
    if (onboardingStore.state.completed) {
      showDashboard = true;
      // Auto-start service when dashboard loads
      serviceStore.start();
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
    serviceStore.start();
  }
</script>

{#if onboardingStore.loading}
  <div class="min-h-screen flex items-center justify-center">
    <div class="text-text-muted">Loading...</div>
  </div>
{:else if showDashboard}
  <Dashboard />
{:else}
  <div class="min-h-screen flex flex-col items-center justify-center p-6">
    <Card padding="none">
      <div class="w-[600px] max-w-full">
        <!-- Step Indicator (not shown on welcome) -->
        {#if currentStep !== "welcome"}
          <div class="px-8 pt-6">
            <StepIndicator
              steps={STEPS.slice(1).map((s) => STEP_LABELS[s])}
              currentStep={currentStepIndex - 1}
            />
          </div>
        {/if}

        <!-- Step Content -->
        <div class="min-h-[400px]">
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
