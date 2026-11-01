import { useEffect, useRef, useState, useCallback } from "react";
import {
  listBatches,
  listMaterials,
  listOperations,
  viewBatchTransfers,
  type BatchView,
  type MaterialView,
  type OperationView,
  type TransferView,
} from "../api/client";
import { buildViewProof } from "../blockchain/viewProof";
import type { NotificationItem } from "./types";
import {
  type PriorState,
  emptyPriorState,
  collectTransferNotifications,
  collectOperationNotifications,
  collectBatchCompletionNotifications,
  collectMaterialCompletionNotifications,
} from "./collector";
import {
  loadSeenIds,
  saveSeenIds,
  loadReadIds,
  saveReadIds,
  loadStoredNotifications,
  saveStoredNotifications,
  clearStoredNotifications,
  isUnread as isUnreadFn,
  unreadCount,
} from "./store";

const POLL_INTERVAL_MS = 20000;

export interface UseNotificationsResult {
  notifications: NotificationItem[];
  unread: number;
  loading: boolean;
  error: string;
  markRead: (id: string) => void;
  markAllRead: () => void;
  clearAll: () => void;
  refresh: () => void;
}

export function useNotifications(
  publicKey: string,
  enabled: boolean,
): UseNotificationsResult {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);

  const priorRef = useRef<PriorState>(emptyPriorState());
  const seenRef = useRef<Set<string>>(new Set());
  const readRef = useRef<Set<string>>(new Set());
  const initializedRef = useRef(false);
  const activeRef = useRef(true);

  // Load persisted state on first call.
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    seenRef.current = loadSeenIds();
    readRef.current = loadReadIds();
    const stored = loadStoredNotifications();
    if (stored.length > 0) {
      // Mark previously-seen notifications as read on restore.
      const restored = stored.map((n) => ({
        ...n,
        read: readRef.current.has(n.id) || seenRef.current.has(n.id),
      }));
      setNotifications(restored);
      setUnread(unreadCount(restored));
    }
  }, []);

  const collect = useCallback(async () => {
    if (!enabled || !publicKey) return;
    setLoading(true);
    setError("");
    try {
      const [b, m, o] = await Promise.all([
        listBatches(),
        listMaterials(),
        listOperations(),
      ]);

      const batches: BatchView[] = b.batches;
      const materials: MaterialView[] = m.materials;
      const operations: OperationView[] = o.operations;

      // Fetch transfers for all batches and materials (view-proof protected).
      const allItemIds = [
        ...batches.map((x) => x.batchId),
        ...materials.map((x) => x.materialId),
      ];
      const transferResults = await Promise.all(
        allItemIds.map((id) =>
          viewBatchTransfers(id, buildViewProof(id))
            .then((r) => r.transfers)
            .catch(() => [] as TransferView[]),
        ),
      );
      const allTransfers = transferResults.flat();

      const prior = priorRef.current;
      const newNotifications: NotificationItem[] = [];

      // Transfer events
      const transferResult = collectTransferNotifications(
        allTransfers,
        prior.transfers,
        publicKey,
      );
      newNotifications.push(...transferResult.notifications);

      // Operation events
      const opResult = collectOperationNotifications(
        operations,
        prior.operations,
        publicKey,
      );
      newNotifications.push(...opResult.notifications);

      // Batch completion
      const batchResult = collectBatchCompletionNotifications(
        batches,
        prior.batches,
      );
      newNotifications.push(...batchResult.notifications);

      // Material completion
      const materialResult = collectMaterialCompletionNotifications(
        materials,
        prior.materials,
      );
      newNotifications.push(...materialResult.notifications);

      // Update prior state
      priorRef.current = {
        transfers: transferResult.next,
        operations: opResult.next,
        batches: batchResult.next,
        materials: materialResult.next,
      };

      // Merge new notifications with deduplication
      if (newNotifications.length > 0) {
        setNotifications((prev) => {
          const existingIds = new Set(prev.map((n) => n.id));
          const seen = seenRef.current;

          const merged: NotificationItem[] = [...prev];
          for (const n of newNotifications) {
            if (!existingIds.has(n.id)) {
              const previouslySeen = seen.has(n.id);
              const finalItem: NotificationItem = {
                ...n,
                read: !isUnreadFn(n.id, readRef.current, previouslySeen),
              };
              merged.unshift(finalItem);
              seen.add(n.id);
            }
          }

          // Sort by createdAt descending
          merged.sort((a, b) =>
            b.createdAt.localeCompare(a.createdAt),
          );

          saveSeenIds(seen);
          saveStoredNotifications(merged);
          setUnread(unreadCount(merged));
          return merged;
        });
      }
    } catch (e) {
      if (activeRef.current) {
        setError(e instanceof Error ? e.message : "Unable to load notifications.");
      }
    } finally {
      if (activeRef.current) setLoading(false);
    }
  }, [enabled, publicKey]);

  // Initial collect + polling
  useEffect(() => {
    activeRef.current = true;
    if (!enabled) return;
    collect();
    const interval = setInterval(() => {
      setTick((t) => t + 1);
    }, POLL_INTERVAL_MS);
    return () => {
      activeRef.current = false;
      clearInterval(interval);
    };
  }, [enabled, collect]);

  // Trigger collect on tick
  useEffect(() => {
    if (tick > 0) collect();
  }, [tick, collect]);

  const markRead = useCallback((id: string) => {
    setNotifications((prev) => {
      const next = prev.map((n) => (n.id === id ? { ...n, read: true } : n));
      readRef.current.add(id);
      saveReadIds(readRef.current);
      saveStoredNotifications(next);
      setUnread(unreadCount(next));
      return next;
    });
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => {
      const next = prev.map((n) => ({ ...n, read: true }));
      for (const n of prev) {
        readRef.current.add(n.id);
      }
      saveReadIds(readRef.current);
      saveStoredNotifications(next);
      setUnread(0);
      return next;
    });
  }, []);

  const clearAll = useCallback(() => {
    clearStoredNotifications();
    seenRef.current = new Set();
    readRef.current = new Set();
    priorRef.current = emptyPriorState();
    setNotifications([]);
    setUnread(0);
  }, []);

  const refresh = useCallback(() => {
    collect();
  }, [collect]);

  return {
    notifications,
    unread,
    loading,
    error,
    markRead,
    markAllRead,
    clearAll,
    refresh,
  };
}
