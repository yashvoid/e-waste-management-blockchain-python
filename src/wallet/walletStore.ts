import type { WalletEnvelope } from "./walletEnvelope";

const DATABASE_NAME = "ewaste-management-wallet";
const STORE_NAME = "wallets";
const DATABASE_VERSION = 1;

let dbPromise: Promise<IDBDatabase> | null = null;

function openDatabase(): Promise<IDBDatabase> {
  if (dbPromise !== null) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "address" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Failed to open wallet storage."));
  });
  return dbPromise;
}

async function withStore<T>(
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, mode);
    const request = fn(tx.objectStore(STORE_NAME));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Wallet storage operation failed."));
  });
}

export async function saveWallet(envelope: WalletEnvelope): Promise<void> {
  await withStore("readwrite", (store) => store.put(envelope));
}

export async function loadWallet(address: string): Promise<WalletEnvelope | undefined> {
  return withStore("readonly", (store) => store.get(address));
}

export async function listWalletAddresses(): Promise<string[]> {
  const keys = await withStore<IDBValidKey[]>("readonly", (store) => store.getAllKeys());
  return keys as string[];
}

export async function deleteWallet(address: string): Promise<void> {
  await withStore("readwrite", (store) => store.delete(address));
}

export function _resetDatabaseConnection(): void {
  dbPromise = null;
}
