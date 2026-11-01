const TOKEN_STORAGE_KEY = "ewaste.operatorToken";

export function getOperatorToken(): string | null {
  return sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setOperatorToken(token: string): void {
  sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearOperatorToken(): void {
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}
