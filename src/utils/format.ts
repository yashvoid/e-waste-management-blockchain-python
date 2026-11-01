export function formatKg(kg: number): string {
  return kg.toFixed(3) + " kg";
}

export function formatGrams(grams: number): string {
  return formatKg(grams / 1000);
}

export function formatTimestamp(iso: string): string {
  if (!iso) return "";
  return iso.replace("T", " ").replace("Z", " UTC");
}

export function shortKey(key: string): string {
  if (key.length <= 16) return key;
  return key.slice(0, 8) + "..." + key.slice(-8);
}

export function gramsToKgInput(grams: number): string {
  return (grams / 1000).toFixed(3);
}

export function kgInputToGrams(kg: string): number {
  const value = parseFloat(kg);
  if (isNaN(value) || value <= 0) return 0;
  return Math.round(value * 1000);
}
