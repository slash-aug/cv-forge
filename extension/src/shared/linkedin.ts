/** True for linkedin.com and any subdomain. Case-insensitive; trailing dots ignored. */
export function isLinkedInHost(host: string): boolean {
  const h = host.toLowerCase().replace(/\.+$/, "");
  return h === "linkedin.com" || h.endsWith(".linkedin.com");
}
