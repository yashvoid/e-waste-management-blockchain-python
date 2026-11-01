import { describe, expect, it, beforeEach, afterEach } from "vitest";

// Minimal test-only sessionStorage polyfill for the Node-based Vitest environment.
// Does not affect production code; only enables store.test.ts to run.
if (typeof sessionStorage === "undefined") {
  let store: Record<string, string> = {};
  (globalThis as Record<string, unknown>).sessionStorage = {
    getItem(key: string) { return store[key] ?? null; },
    setItem(key: string, value: string) { store[key] = String(value); },
    removeItem(key: string) { delete store[key]; },
    clear() { store = {}; },
  };
}

import {
  loadSeenIds,
  saveSeenIds,
  loadReadIds,
  saveReadIds,
  loadStoredNotifications,
  saveStoredNotifications,
  clearStoredNotifications,
  notificationKey,
  isUnread,
  markItemRead,
  markAllRead,
  unreadCount,
} from "./store";
import type { NotificationItem } from "./types";

function makeNotification(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: "test-1",
    category: "incoming-transfer",
    title: "Test notification",
    detail: "Test detail",
    createdAt: "2026-11-01T10:00:00Z",
    read: false,
    ...overrides,
  };
}

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  sessionStorage.clear();
});

describe("sessionStorage seen/read persistence", () => {
  it("saves and loads seen ids", () => {
    const seen = new Set(["a", "b"]);
    saveSeenIds(seen);
    const loaded = loadSeenIds();
    expect(loaded).toEqual(new Set(["a", "b"]));
  });

  it("returns empty set when nothing is stored", () => {
    expect(loadSeenIds()).toEqual(new Set());
  });

  it("saves and loads read ids", () => {
    const read = new Set(["x"]);
    saveReadIds(read);
    expect(loadReadIds()).toEqual(new Set(["x"]));
  });

  it("returns empty set when nothing is stored", () => {
    expect(loadReadIds()).toEqual(new Set());
  });
});

describe("stored notifications", () => {
  it("saves and loads notifications", () => {
    const items = [makeNotification({ id: "n1" }), makeNotification({ id: "n2" })];
    saveStoredNotifications(items);
    const loaded = loadStoredNotifications();
    expect(loaded).toHaveLength(2);
    expect(loaded[0].id).toBe("n1");
    expect(loaded[1].id).toBe("n2");
  });

  it("returns empty array when nothing is stored", () => {
    expect(loadStoredNotifications()).toEqual([]);
  });

  it("trims to 200 notifications", () => {
    const items: NotificationItem[] = [];
    for (let i = 0; i < 250; i++) {
      items.push(makeNotification({ id: `n${i}` }));
    }
    saveStoredNotifications(items);
    const loaded = loadStoredNotifications();
    expect(loaded).toHaveLength(200);
    expect(loaded[0].id).toBe("n0");
  });
});

describe("clearStoredNotifications", () => {
  it("removes all stored notification data", () => {
    saveSeenIds(new Set(["a"]));
    saveReadIds(new Set(["b"]));
    saveStoredNotifications([makeNotification()]);
    clearStoredNotifications();
    expect(loadSeenIds()).toEqual(new Set());
    expect(loadReadIds()).toEqual(new Set());
    expect(loadStoredNotifications()).toEqual([]);
  });
});

describe("isUnread", () => {
  it("is unread when not in readIds and not previously seen", () => {
    expect(isUnread("n1", new Set(), false)).toBe(true);
  });

  it("is read when in readIds", () => {
    expect(isUnread("n1", new Set(["n1"]), false)).toBe(false);
  });

  it("is read when previously seen (already surfaced in a prior session)", () => {
    expect(isUnread("n1", new Set(), true)).toBe(false);
  });
});

describe("markItemRead", () => {
  it("marks a single item as read", () => {
    const items = [makeNotification({ id: "n1", read: false }), makeNotification({ id: "n2", read: false })];
    const readIds = new Set<string>();
    const result = markItemRead(items, readIds, "n1");
    expect(result.items[0].read).toBe(true);
    expect(result.items[1].read).toBe(false);
    expect(result.readIds.has("n1")).toBe(true);
  });
});

describe("markAllRead", () => {
  it("marks all items as read", () => {
    const items = [makeNotification({ id: "n1", read: false }), makeNotification({ id: "n2", read: false })];
    const readIds = new Set<string>();
    const result = markAllRead(items, readIds);
    expect(result.items.every((n) => n.read)).toBe(true);
    expect(result.readIds.has("n1")).toBe(true);
    expect(result.readIds.has("n2")).toBe(true);
  });
});

describe("unreadCount", () => {
  it("counts unread notifications", () => {
    const items = [makeNotification({ id: "n1", read: false }), makeNotification({ id: "n2", read: true }), makeNotification({ id: "n3", read: false })];
    expect(unreadCount(items)).toBe(2);
  });

  it("returns 0 when all are read", () => {
    const items = [makeNotification({ id: "n1", read: true }), makeNotification({ id: "n2", read: true })];
    expect(unreadCount(items)).toBe(0);
  });

  it("returns 0 for empty list", () => {
    expect(unreadCount([])).toBe(0);
  });
});

describe("notificationKey deduplication", () => {
  it("produces identical keys for the same category and ids", () => {
    const k1 = notificationKey("transfer-accepted", { transferId: "t1", batchId: "b1" });
    const k2 = notificationKey("transfer-accepted", { transferId: "t1", batchId: "b1" });
    expect(k1).toBe(k2);
  });

  it("produces different keys for different transfer ids", () => {
    const k1 = notificationKey("transfer-accepted", { transferId: "t1" });
    const k2 = notificationKey("transfer-accepted", { transferId: "t2" });
    expect(k1).not.toBe(k2);
  });
});
