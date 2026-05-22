const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL;

export const API_BASE_URL =
  typeof rawApiBaseUrl === "string" && rawApiBaseUrl.trim() !== ""
    ? rawApiBaseUrl.replace(/\/+$/, "")
    : "http://localhost:8001";

type QueryValue = string | number | boolean | null | undefined;

export function apiUrl(
  path: string,
  query?: Record<string, QueryValue>,
): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${API_BASE_URL}${normalizedPath}`;

  if (!query) return url;

  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });

  const queryString = params.toString();
  return queryString ? `${url}?${queryString}` : url;
}

export function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}
