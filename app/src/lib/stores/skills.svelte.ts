import { Command } from "@tauri-apps/plugin-shell";
import { join, homeDir, resourceDir, dirname } from "@tauri-apps/api/path";
import { readTextFile, writeTextFile, mkdir, readDir, exists } from "@tauri-apps/plugin-fs";

export interface Skill {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  is_builtin: boolean;
  apps: string[];
  tasks: string[];
  examples: string[];
  safe_defaults: Record<string, unknown>;
  confirm_before_write: string[];
  source_path: string | null;
  body?: string;
}

interface SkillsConfig {
  enabled_skills: Record<string, boolean>;
}

// Built-in skills (hardcoded for fast UI loading)
const BUILTIN_SKILLS: Omit<Skill, "enabled" | "source_path">[] = [
  {
    id: "mail_assistant",
    name: "Mail Assistant",
    description: "Find, summarize, and act on emails safely with sensible defaults.",
    is_builtin: true,
    apps: ["Mail"],
    tasks: ["search_emails", "send_email", "move_email", "download_attachments", "get_unread_emails", "mark_emails_read"],
    examples: [
      "Summarize unread emails from today",
      "Find emails from UPS and show tracking numbers",
      "Archive all read newsletters",
    ],
    safe_defaults: { days: 7, limit: 20, with_content: false },
    confirm_before_write: ["send email", "delete email", "move to trash"],
  },
  {
    id: "calendar_assistant",
    name: "Calendar Assistant",
    description: "View and manage calendar events with smart scheduling defaults.",
    is_builtin: true,
    apps: ["Calendar"],
    tasks: ["get_today_events", "get_week_events", "create_calendar_event", "list_calendars"],
    examples: [
      "What's on my calendar today?",
      "Show me my schedule for this week",
      "Create a meeting with John tomorrow at 2pm",
    ],
    safe_defaults: { days_ahead: 7, include_all_day: true },
    confirm_before_write: ["create event", "delete event", "modify event"],
  },
  {
    id: "reminders_assistant",
    name: "Reminders Assistant",
    description: "Create and manage reminders with natural language time parsing.",
    is_builtin: true,
    apps: ["Reminders"],
    tasks: ["create_reminder", "list_reminders", "complete_reminder", "get_due_today_reminders"],
    examples: [
      "Remind me to call mom at 5pm",
      "Show my reminders for today",
      "Mark the grocery reminder as done",
    ],
    safe_defaults: { list: "Reminders", include_completed: false },
    confirm_before_write: ["delete reminder"],
  },
  {
    id: "notes_assistant",
    name: "Notes Assistant",
    description: "Search and create notes in Apple Notes.",
    is_builtin: true,
    apps: ["Notes"],
    tasks: ["search_notes", "create_note", "list_notes"],
    examples: [
      "Search my notes for the wifi password",
      "Create a note about today's meeting",
      "Show me my recent notes",
    ],
    safe_defaults: { limit: 20, folder: "Notes" },
    confirm_before_write: ["delete note"],
  },
  {
    id: "safari_assistant",
    name: "Safari Assistant",
    description: "Control Safari tabs, open URLs, and perform web searches.",
    is_builtin: true,
    apps: ["Safari"],
    tasks: ["open_url_in_safari", "list_safari_tabs", "get_current_safari_page", "extract_safari_links", "web_search", "web_fetch"],
    examples: [
      "Open GitHub in Safari",
      "Show me my open tabs",
      "Search the web for Python tutorials",
    ],
    safe_defaults: { new_tab: true, timeout: 30 },
    confirm_before_write: ["close all tabs"],
  },
  {
    id: "browser_automation",
    name: "Browser Automation",
    description: "Automate web interactions for bookings, form submissions, and purchases.",
    is_builtin: true,
    apps: ["Safari"],
    tasks: ["browser_navigate", "browser_snapshot", "browser_click", "browser_type", "browser_select", "browser_scroll_to"],
    examples: [
      "Book a table at Restaurant XYZ for Friday at 7pm",
      "Fill out the contact form on this page",
    ],
    safe_defaults: { timeout: 20, max_elements: 200 },
    confirm_before_write: ["submit form", "complete purchase", "confirm booking"],
  },
];

class SkillsStore {
  private _skills = $state<Skill[]>([]);
  private _loading = $state(false);
  private _error = $state<string | null>(null);
  private _config: SkillsConfig = { enabled_skills: {} };
  private _macbotDir: string | null = null;

  get skills() {
    return this._skills;
  }

  get loading() {
    return this._loading;
  }

  get error() {
    return this._error;
  }

  get enabledCount() {
    return this._skills.filter((s) => s.enabled).length;
  }

  get totalCount() {
    return this._skills.length;
  }

  private async getMacbotDir(): Promise<string> {
    if (this._macbotDir) return this._macbotDir;
    const home = await homeDir();
    this._macbotDir = await join(home, ".macbot");
    return this._macbotDir;
  }

  private async loadConfig(): Promise<void> {
    try {
      const macbotDir = await getMacbotDir();
      const configPath = await join(macbotDir, "skills.json");
      if (await exists(configPath)) {
        const content = await readTextFile(configPath);
        const parsed = JSON.parse(content);
        // Ensure the config has the expected structure
        this._config = {
          enabled_skills: parsed.enabled_skills && typeof parsed.enabled_skills === "object"
            ? parsed.enabled_skills
            : {}
        };
      }
    } catch (e) {
      console.warn("Could not load skills config:", e);
      this._config = { enabled_skills: {} };
    }
  }

  private async saveConfig(): Promise<void> {
    try {
      const macbotDir = await this.getMacbotDir();
      const configPath = await join(macbotDir, "skills.json");
      await mkdir(macbotDir, { recursive: true });
      await writeTextFile(configPath, JSON.stringify(this._config, null, 2));
    } catch (e) {
      console.error("Could not save skills config:", e);
    }
  }

  private isEnabled(skillId: string, defaultValue: boolean = true): boolean {
    if (skillId in this._config.enabled_skills) {
      return this._config.enabled_skills[skillId];
    }
    return defaultValue;
  }

  private parseSkillFile(content: string, sourcePath: string): Skill | null {
    // Parse YAML frontmatter
    const match = content.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)/);
    if (!match) return null;

    const yamlContent = match[1];
    const body = match[2]?.trim() || "";

    // Simple YAML parsing for our known fields
    const getValue = (key: string): string | null => {
      const regex = new RegExp(`^${key}:\\s*(.+)$`, "m");
      const m = yamlContent.match(regex);
      return m ? m[1].trim() : null;
    };

    const getList = (key: string): string[] => {
      const regex = new RegExp(`^${key}:\\s*\\n((?:\\s+-\\s+.+\\n?)*)`, "m");
      const m = yamlContent.match(regex);
      if (!m) return [];
      return m[1]
        .split("\n")
        .map((line) => line.replace(/^\s*-\s*/, "").trim())
        .filter((line) => line && !line.startsWith("#"))
        .map((line) => line.replace(/^["']|["']$/g, "")); // Remove quotes
    };

    const getObject = (key: string): Record<string, unknown> => {
      const regex = new RegExp(`^${key}:\\s*\\n((?:\\s+\\w+:.+\\n?)*)`, "m");
      const m = yamlContent.match(regex);
      if (!m) return {};
      const obj: Record<string, unknown> = {};
      m[1].split("\n").forEach((line) => {
        const kvMatch = line.match(/^\s+(\w+):\s*(.+)$/);
        if (kvMatch) {
          const v = kvMatch[2].trim();
          // Try to parse as JSON, otherwise keep as string
          try {
            obj[kvMatch[1]] = JSON.parse(v);
          } catch {
            obj[kvMatch[1]] = v;
          }
        }
      });
      return obj;
    };

    const id = getValue("id");
    const name = getValue("name");
    const description = getValue("description");

    if (!id || !name || !description) return null;

    return {
      id,
      name,
      description,
      enabled: this.isEnabled(id),
      is_builtin: false,
      apps: getList("apps"),
      tasks: getList("tasks"),
      examples: getList("examples"),
      safe_defaults: getObject("safe_defaults"),
      confirm_before_write: getList("confirm_before_write"),
      source_path: sourcePath,
      body,
    };
  }

  private async loadUserSkills(): Promise<Skill[]> {
    const skills: Skill[] = [];
    try {
      const macbotDir = await this.getMacbotDir();
      const skillsDir = await join(macbotDir, "skills");

      if (!(await exists(skillsDir))) {
        return skills;
      }

      const entries = await readDir(skillsDir);
      for (const entry of entries) {
        if (entry.isDirectory && entry.name) {
          const skillPath = await join(skillsDir, entry.name, "SKILL.md");
          try {
            if (await exists(skillPath)) {
              const content = await readTextFile(skillPath);
              const skill = this.parseSkillFile(content, skillPath);
              if (skill) {
                skills.push(skill);
              } else {
                console.warn(`Skipping malformed skill at ${skillPath}`);
              }
            }
          } catch (e) {
            console.warn(`Could not read skill at ${skillPath}:`, e);
          }
        }
      }
    } catch (e) {
      console.warn("Could not load user skills:", e);
    }
    return skills;
  }

  async load() {
    this._loading = true;
    this._error = null;

    try {
      await this.loadConfig();

      // Start with built-in skills
      const builtinSkills: Skill[] = BUILTIN_SKILLS.map((s) => ({
        ...s,
        enabled: this.isEnabled(s.id),
        source_path: null,
      }));

      // Load user skills
      const userSkills = await this.loadUserSkills();

      // Merge: user skills override built-in by ID
      const skillMap = new Map<string, Skill>();
      for (const skill of builtinSkills) {
        skillMap.set(skill.id, skill);
      }
      for (const skill of userSkills) {
        skillMap.set(skill.id, skill);
      }

      this._skills = Array.from(skillMap.values()).sort((a, b) => a.name.localeCompare(b.name));
    } catch (e) {
      this._error = `Failed to load skills: ${e}`;
      console.error("Failed to load skills:", e);
    } finally {
      this._loading = false;
    }
  }

  async enable(skillId: string) {
    this._config.enabled_skills[skillId] = true;
    await this.saveConfig();

    // Update local state
    const skill = this._skills.find((s) => s.id === skillId);
    if (skill) {
      skill.enabled = true;
    }

    await this.signalReload();
  }

  async disable(skillId: string) {
    this._config.enabled_skills[skillId] = false;
    await this.saveConfig();

    // Update local state
    const skill = this._skills.find((s) => s.id === skillId);
    if (skill) {
      skill.enabled = false;
    }

    await this.signalReload();
  }

  async toggle(skillId: string) {
    const skill = this._skills.find((s) => s.id === skillId);
    if (!skill) return;

    if (skill.enabled) {
      await this.disable(skillId);
    } else {
      await this.enable(skillId);
    }
  }

  async readSkillContent(skillId: string): Promise<string | null> {
    const skill = this._skills.find((s) => s.id === skillId);
    if (!skill?.source_path) return null;

    try {
      return await readTextFile(skill.source_path);
    } catch (e) {
      console.error("Failed to read skill content:", e);
      return null;
    }
  }

  async writeSkillContent(skillId: string, content: string): Promise<{ success: boolean; error?: string }> {
    try {
      // Validate that content has required fields before saving
      const idMatch = content.match(/^id:\s*(\S+)/m);
      if (!idMatch) {
        return { success: false, error: "YAML frontmatter must include an 'id' field (required)" };
      }
      const actualId = idMatch[1];

      const nameMatch = content.match(/^name:\s*(.+)/m);
      if (!nameMatch) {
        return { success: false, error: "YAML frontmatter must include a 'name' field" };
      }

      const descMatch = content.match(/^description:\s*(.+)/m);
      if (!descMatch) {
        return { success: false, error: "YAML frontmatter must include a 'description' field" };
      }

      // User skills go to ~/.macbot/skills/<skill_id>/SKILL.md
      const macbotDir = await this.getMacbotDir();
      const skillDir = await join(macbotDir, "skills", actualId);
      const skillPath = await join(skillDir, "SKILL.md");

      // Create directory if needed
      await mkdir(skillDir, { recursive: true });

      // Write the file
      await writeTextFile(skillPath, content);

      // Signal running service to reload
      await this.signalReload();

      // Reload our local list
      await this.load();

      return { success: true };
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : String(e);
      this._error = `Failed to write skill: ${errorMsg}`;
      console.error("Failed to write skill content:", e);
      return { success: false, error: errorMsg };
    }
  }

  async deleteSkill(skillId: string): Promise<{ success: boolean; error?: string }> {
    try {
      const skill = this._skills.find((s) => s.id === skillId);
      if (!skill) {
        return { success: false, error: "Skill not found" };
      }
      if (skill.is_builtin && !skill.source_path) {
        return { success: false, error: "Cannot delete built-in skill" };
      }

      // For user skills, remove the directory
      const macbotDir = await this.getMacbotDir();
      const skillDir = await join(macbotDir, "skills", skillId);

      // Use shell to remove directory (fs plugin doesn't have rmdir)
      const cmd = Command.create("exec-sh", ["-c", `rm -rf "${skillDir}"`]);
      await cmd.execute();

      // Signal running service to reload
      await this.signalReload();

      // Reload our local list
      await this.load();

      return { success: true };
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : String(e);
      return { success: false, error: errorMsg };
    }
  }

  private async signalReload(): Promise<void> {
    try {
      // Send SIGHUP to running service via CLI (lightweight operation)
      const home = await homeDir();
      const pidFile = await join(home, ".macbot", "service.pid");

      if (await exists(pidFile)) {
        const pid = await readTextFile(pidFile);
        const cmd = Command.create("exec-sh", ["-c", `kill -HUP ${pid.trim()} 2>/dev/null || true`]);
        await cmd.execute();
      }
    } catch (e) {
      console.warn("Could not signal service reload:", e);
    }
  }
}

// Helper function to avoid 'this' issues in loadConfig
async function getMacbotDir(): Promise<string> {
  const home = await homeDir();
  return join(home, ".macbot");
}

export const skillsStore = new SkillsStore();
