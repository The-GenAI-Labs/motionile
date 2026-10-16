export const readCookie = (name: string): string | null => {
  if (typeof document === "undefined") return null;
  const value = document.cookie.split("; ").find((cookie) => cookie.startsWith(`${name}=`));
  if (!value) return null;
  try {
    return decodeURIComponent(value.slice(name.length + 1));
  } catch {
    return null;
  }
};

export const readAccessExpiry = (): number | null => {
  const value = readCookie("mo_auth");
  if (!value || !/^\d+$/.test(value)) return null;
  const seconds = Number(value);
  return Number.isSafeInteger(seconds) && seconds > 0 ? seconds * 1000 : null;
};
