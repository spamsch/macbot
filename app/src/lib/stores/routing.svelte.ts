import { homeDir, join } from "@tauri-apps/api/path";
import { readTextFile, writeTextFile, exists, mkdir } from "@tauri-apps/plugin-fs";

export interface Route {
  name: string;
  skills: string[];
  model: string;
}

interface RoutingConfig {
  routes: Route[];
}

class RoutingStore {
  private _routes = $state<Route[]>([]);
  private _loading = $state(false);
  private _saving = $state(false);
  private _error = $state<string | null>(null);
  private _dirty = $state(false);
  private _filePath: string | null = null;

  get routes() {
    return this._routes;
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

  get hasRoutes() {
    return this._routes.length > 0;
  }

  private async getFilePath(): Promise<string> {
    if (this._filePath) return this._filePath;
    const home = await homeDir();
    this._filePath = await join(home, ".macbot", "routing.json");
    return this._filePath;
  }

  async load() {
    this._loading = true;
    this._error = null;

    try {
      const filePath = await this.getFilePath();

      if (await exists(filePath)) {
        const content = await readTextFile(filePath);
        const parsed: RoutingConfig = JSON.parse(content);
        this._routes = parsed.routes || [];
      } else {
        this._routes = [];
      }

      this._dirty = false;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this._error = `Failed to load routing config: ${msg}`;
      console.error("Failed to load routing config:", e);
      this._routes = [];
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

      const config: RoutingConfig = { routes: this._routes };
      await writeTextFile(filePath, JSON.stringify(config, null, 2) + "\n");
      this._dirty = false;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this._error = `Failed to save routing config: ${msg}`;
      console.error("Failed to save routing config:", e);
    } finally {
      this._saving = false;
    }
  }

  addRoute() {
    this._routes = [
      ...this._routes,
      { name: "New Route", skills: [], model: "" },
    ];
    this._dirty = true;
  }

  removeRoute(index: number) {
    this._routes = this._routes.filter((_, i) => i !== index);
    this._dirty = true;
  }

  updateRoute(index: number, updates: Partial<Route>) {
    this._routes = this._routes.map((r, i) =>
      i === index ? { ...r, ...updates } : r,
    );
    this._dirty = true;
  }

  moveRoute(index: number, direction: "up" | "down") {
    const newIndex = direction === "up" ? index - 1 : index + 1;
    if (newIndex < 0 || newIndex >= this._routes.length) return;

    const newRoutes = [...this._routes];
    [newRoutes[index], newRoutes[newIndex]] = [
      newRoutes[newIndex],
      newRoutes[index],
    ];
    this._routes = newRoutes;
    this._dirty = true;
  }
}

export const routingStore = new RoutingStore();
