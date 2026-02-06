import { homeDir, join } from "@tauri-apps/api/path";
import { readTextFile, writeTextFile, exists, mkdir } from "@tauri-apps/plugin-fs";

class HeartbeatStore {
  private _content = $state("");
  private _loading = $state(false);
  private _saving = $state(false);
  private _error = $state<string | null>(null);
  private _dirty = $state(false);
  private _filePath: string | null = null;

  get content() {
    return this._content;
  }

  get loading() {
    return this._loading;
  }

  get saving() {
    return this._saving;
  }

  get error() {
    return this._error;
  }

  get dirty() {
    return this._dirty;
  }

  setContent(value: string) {
    this._content = value;
    this._dirty = true;
  }

  private async getFilePath(): Promise<string> {
    if (this._filePath) return this._filePath;
    const home = await homeDir();
    this._filePath = await join(home, ".macbot", "heartbeat.md");
    return this._filePath;
  }

  async load() {
    this._loading = true;
    this._error = null;

    try {
      const filePath = await this.getFilePath();

      if (await exists(filePath)) {
        this._content = await readTextFile(filePath);
      } else {
        this._content = "";
      }

      this._dirty = false;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this._error = `Failed to load heartbeat: ${msg}`;
      console.error("Failed to load heartbeat:", e);
    } finally {
      this._loading = false;
    }
  }

  async save() {
    this._saving = true;
    this._error = null;

    try {
      const filePath = await this.getFilePath();

      const home = await homeDir();
      const macbotDir = await join(home, ".macbot");
      await mkdir(macbotDir, { recursive: true });

      await writeTextFile(filePath, this._content);
      this._dirty = false;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this._error = `Failed to save heartbeat: ${msg}`;
      console.error("Failed to save heartbeat:", e);
    } finally {
      this._saving = false;
    }
  }
}

export const heartbeatStore = new HeartbeatStore();
