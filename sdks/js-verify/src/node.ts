/**
 * Node-only helpers (clock state file, stable machine id). Loaded lazily with dynamic import so
 * the core verifier stays runtime-agnostic; in browsers/edge runtimes they degrade to memory/no-op.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

async function load(name: string): Promise<Any | null> {
  try {
    return await import(name);
  } catch {
    return null;
  }
}

function env(name: string): string | undefined {
  const v = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.[name];
  return v && v.trim() ? v.trim() : undefined;
}

/** Monotonic "latest time seen" store used to detect clocks set backwards. */
export interface ClockGuard {
  lastSeen(): Promise<number | undefined>;
  record(now: number): Promise<void>;
}

/**
 * File-backed clock guard: `KEYFLINT_CLOCK_STATE` or `~/.keyflint/clock_state` ("off" = memory only).
 * Same file format as the Python package: {"v": 1, "last_seen": <unix seconds>}.
 * Limits: whoever controls the machine can delete the file; a fresh container has no state.
 */
export function createClockGuard(path?: string | null): ClockGuard {
  let mem: number | undefined;
  let resolved: Promise<string | null> | undefined;
  const filePath = (): Promise<string | null> =>
    (resolved ??= (async () => {
      if (path === null) return null;
      if (path) return path;
      const raw = env("KEYFLINT_CLOCK_STATE");
      if (raw !== undefined) return ["off", "0", "false"].includes(raw.toLowerCase()) ? null : raw;
      const os = await load("node:os");
      const p = await load("node:path");
      if (!os || !p) return null;
      try {
        return p.join(os.homedir(), ".keyflint", "clock_state") as string;
      } catch {
        return null;
      }
    })());

  async function readDisk(): Promise<number | undefined> {
    const f = await filePath();
    const fs = f ? await load("node:fs/promises") : null;
    if (!f || !fs) return undefined;
    try {
      const v = (JSON.parse(await fs.readFile(f, "utf8")) as { last_seen?: unknown }).last_seen;
      return typeof v === "number" && Number.isFinite(v) ? Math.floor(v) : undefined;
    } catch {
      return undefined;
    }
  }

  return {
    async lastSeen() {
      const disk = await readDisk();
      const vals = [mem, disk].filter((v): v is number => v !== undefined);
      return vals.length ? Math.max(...vals) : undefined;
    },
    async record(now: number) {
      const current = Math.floor(now);
      if (mem !== undefined && current <= mem) return;
      const disk = await readDisk();
      mem = Math.max(current, disk ?? 0);
      const f = await filePath();
      if (!f || (disk !== undefined && disk >= current)) return;
      const fs = await load("node:fs/promises");
      const p = await load("node:path");
      if (!fs || !p) return;
      try {
        await fs.mkdir(p.dirname(f), { recursive: true });
        const tmp = `${f}.${Math.random().toString(16).slice(2)}.tmp`;
        await fs.writeFile(tmp, JSON.stringify({ v: 1, last_seen: current }));
        await fs.rename(tmp, f);
      } catch {
        /* read-only file system: keep the in-memory value */
      }
    },
  };
}

async function hostId(): Promise<string | undefined> {
  const explicit = env("KEYFLINT_HOST_ID");
  if (explicit) return `env:${explicit}`;
  const proc = (globalThis as { process?: { platform?: string } }).process;
  const platform = proc?.platform;
  const cp = await load("node:child_process");
  if (platform === "win32" && cp) {
    try {
      const out: string = cp.execFileSync("reg", ["query", "HKLM\\SOFTWARE\\Microsoft\\Cryptography", "/v", "MachineGuid"],
        { encoding: "utf8", timeout: 3000 });
      const m = /MachineGuid\s+REG_SZ\s+(\S+)/i.exec(out);
      return m?.[1] ? `win:${m[1].toLowerCase()}` : undefined;
    } catch {
      return undefined;
    }
  }
  if (platform === "darwin" && cp) {
    try {
      const out: string = cp.execFileSync("ioreg", ["-rd1", "-c", "IOPlatformExpertDevice"], { encoding: "utf8", timeout: 3000 });
      const m = /"IOPlatformUUID"\s*=\s*"([^"]+)"/.exec(out);
      return m?.[1] ? `mac:${m[1].toLowerCase()}` : undefined;
    } catch {
      return undefined;
    }
  }
  const fs = await load("node:fs/promises");
  if (fs) {
    for (const f of ["/etc/machine-id", "/var/lib/dbus/machine-id"]) {
      try {
        const v = (await fs.readFile(f, "ascii")).trim().toLowerCase();
        if (v && !/^0+$/.test(v)) return `linux:${v}`;
      } catch {
        /* next */
      }
    }
  }
  const codespace = env("CODESPACE_NAME");
  return codespace ? `codespace:${codespace.toLowerCase()}` : undefined;
}

/**
 * Host-level machine id that survives container/devcontainer rebuilds (Windows MachineGuid,
 * macOS IOPlatformUUID, Linux/WSL /etc/machine-id, CODESPACE_NAME or KEYFLINT_HOST_ID).
 * Identical to the Python package's `compute_machine_id(strategy="stable")`. Undefined when no
 * host id is visible (mount /etc/machine-id read-only into the container, or set KEYFLINT_HOST_ID).
 */
export async function stableMachineId(): Promise<string | undefined> {
  const host = await hostId();
  const subtle = (globalThis as { crypto?: { subtle?: SubtleCrypto } }).crypto?.subtle;
  if (!host || !subtle) return undefined;
  const digest = await subtle.digest("SHA-256", new TextEncoder().encode(`keyflint-stable:${host}`));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
