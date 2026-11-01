import type { NotificationItem, NotificationCategory } from "./types";

/**
 * Notification deduplication and unread/read state.
 *
 * Each notification has a deterministic key derived from the event (category +
 * IDs).  This prevents duplicate notifications when the same data is fetched
 * repeatedly through polling.  Notifications are kept in-memory and the set of
 * *seen* notification IDs is persisted to `sessionStorage` so duplicates remain
 * suppressed across manual page refreshes within the same browser session.
 * Read state is also persisted to `sessionStorage`.
 *
 * No new database, server, or persistence infrastructure is introduced.  When
 * the browser tab is closed the notification list and seen-state are lost,
 * which is acceptable for a polling-based notification area.
 */

const STORAGE_KEY = "ewaste-notifications-v1";
const SEEN_KEY = "ewaste-notification-seen-v1";
const READ_KEY = "ewaste-notification-read-v1";

export function notificationKey(
  category: NotificationCategory,
  ids: Record<string, string | undefined>,
): string {
  const parts: string[] = [category];
  for (const key of Object.keys(ids).sort()) {
    const val = ids[key];
    if (val !== undefined && val !== "") parts.push(`${key}:${val}`);
  }
  return parts.join("|");
}

export interface NotificationStore {
  notifications: NotificationItem[];
  seenIds: Set<string>;
  readIds: Set<string>;
}

export function loadSeenIds(): Set<string> {
  try {
    const raw = sessionStorage.getItem(SEEN_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(arr);
  } catch {
    return new Set();
  }
}

export function saveSeenIds(seenIds: Set<string>): void {
  try {
    sessionStorage.setItem(SEEN_KEY, JSON.stringify([...seenIds]));
  } catch {
    // sessionStorage may be unavailable (private mode); ignore
  }
}

export function loadReadIds(): Set<string> {
  try {
    const raw = sessionStorage.getItem(READ_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(arr);
  } catch {
    return new Set();
  }
}

export function saveReadIds(readIds: Set<string>): void {
  try {
    sessionStorage.setItem(READ_KEY, JSON.stringify([...readIds]));
  } catch {
    // ignore
  }
}

export function loadStoredNotifications(): NotificationItem[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as NotificationItem[];
  } catch {
    return [];
  }
}

export function saveStoredNotifications(items: NotificationItem[]): void {
  try {
    // Keep only the most recent 200 notifications to avoid unbounded growth.
    const trimmed = items.slice(0, 200);
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch {
    // ignore
  }
}

export function clearStoredNotifications(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem(SEEN_KEY);
    sessionStorage.removeItem(READ_KEY);
  } catch {
    // ignore
  }
}

export function isUnread(
  id: string,
  readIds: Set<string>,
  previouslySeen: boolean,
): boolean {
  if (readIds.has(id)) return false;
  // A notification that was already seen in a prior session is treated as read
  // (it was surfaced to the participant before).  Only newly-seen
  // notifications appear as unread.
  return !previouslySeen;
}

export function markItemRead(
  items: NotificationItem[],
  readIds: Set<string>,
  id: string,
): { items: NotificationItem[]; readIds: Set<string> } {
  const next = items.map((n) => (n.id === id ? { ...n, read: true } : n));
  const updated = new Set(readIds);
  updated.add(id);
  return { items: next, readIds: updated };
}

export function markAllRead(
  items: NotificationItem[],
  readIds: Set<string>,
): { items: NotificationItem[]; readIds: Set<string> } {
  const updated = new Set(readIds);
  for (const n of items) {
    updated.add(n.id);
  }
  const next = items.map((n) => ({ ...n, read: true }));
  return { items: next, readIds: updated };
}

export function unreadCount(items: NotificationItem[]): number {
  return items.filter((n) => !n.read).length;
}

export function formatListTimestamp(iso: string): string {
  if (!iso) return "";
  return iso.replace("T", " ").replace("Z", " UTC");
}
