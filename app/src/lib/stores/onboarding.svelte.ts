import { invoke } from "@tauri-apps/api/core";

// Types matching Rust structs
export interface PermissionsData {
  accessibility: boolean;
  automation: Record<string, boolean>;
}

export interface ApiKeyData {
  provider: string;
  configured: boolean;
  verified: boolean;
}

export interface TelegramData {
  configured: boolean;
  skipped: boolean;
}

export interface OnboardingData {
  permissions: PermissionsData;
  api_key: ApiKeyData;
  telegram: TelegramData;
}

export interface OnboardingState {
  version: number;
  completed: boolean;
  current_step: string;
  data: OnboardingData;
}

export type Step = "welcome" | "permissions" | "apikey" | "telegram" | "complete";

export const STEPS: Step[] = ["welcome", "permissions", "apikey", "telegram", "complete"];

export const STEP_LABELS: Record<Step, string> = {
  welcome: "Welcome",
  permissions: "Permissions",
  apikey: "API Key",
  telegram: "Telegram",
  complete: "Complete",
};

// Default state
function createDefaultState(): OnboardingState {
  return {
    version: 1,
    completed: false,
    current_step: "welcome",
    data: {
      permissions: {
        accessibility: false,
        automation: {
          Mail: false,
          Calendar: false,
          Reminders: false,
          Notes: false,
          Safari: false,
        },
      },
      api_key: {
        provider: "anthropic",
        configured: false,
        verified: false,
      },
      telegram: {
        configured: false,
        skipped: false,
      },
    },
  };
}

// Svelte 5 reactive state with persistence
class OnboardingStore {
  private _state = $state<OnboardingState>(createDefaultState());
  private _loading = $state(true);
  private _error = $state<string | null>(null);

  get state() {
    return this._state;
  }

  get loading() {
    return this._loading;
  }

  get error() {
    return this._error;
  }

  get currentStepIndex() {
    return STEPS.indexOf(this._state.current_step as Step);
  }

  async load() {
    this._loading = true;
    this._error = null;
    console.log("[Onboarding] Starting load...");
    try {
      const state = await invoke<OnboardingState>("read_onboarding_state");
      console.log("[Onboarding] Loaded state:", state);
      this._state = state;
    } catch (e) {
      console.error("[Onboarding] Failed to load state:", e);
      this._error = String(e);
      this._state = createDefaultState();
      console.log("[Onboarding] Using default state");
    } finally {
      this._loading = false;
      console.log("[Onboarding] Loading complete, loading =", this._loading);
    }
  }

  private async save() {
    try {
      await invoke("write_onboarding_state", { state: this._state });
    } catch (e) {
      console.error("Failed to save onboarding state:", e);
      this._error = String(e);
    }
  }

  async setStep(step: Step) {
    this._state.current_step = step;
    await this.save();
  }

  async nextStep() {
    const currentIndex = this.currentStepIndex;
    if (currentIndex < STEPS.length - 1) {
      await this.setStep(STEPS[currentIndex + 1]);
    }
  }

  async prevStep() {
    const currentIndex = this.currentStepIndex;
    if (currentIndex > 0) {
      await this.setStep(STEPS[currentIndex - 1]);
    }
  }

  async updatePermissions(permissions: Partial<PermissionsData>) {
    this._state.data.permissions = {
      ...this._state.data.permissions,
      ...permissions,
    };
    await this.save();
  }

  async updateApiKey(apiKey: Partial<ApiKeyData>) {
    this._state.data.api_key = {
      ...this._state.data.api_key,
      ...apiKey,
    };
    await this.save();
  }

  async updateTelegram(telegram: Partial<TelegramData>) {
    this._state.data.telegram = {
      ...this._state.data.telegram,
      ...telegram,
    };
    await this.save();
  }

  async complete() {
    this._state.completed = true;
    this._state.current_step = "complete";
    await this.save();
  }

  async reset() {
    this._state = createDefaultState();
    await this.save();
  }
}

export const onboardingStore = new OnboardingStore();
