/**
 * The registrable domain, approximated: the last two host labels, or the last three when the
 * last is a 2-letter ccTLD and the second-last has 2-3 letters (example.com.br, example.co.uk).
 */
export function siteOf(host: string): string {
  const labels = host.toLowerCase().replace(/\.+$/, "").split(".");
  const last = labels.at(-1) ?? "";
  const second = labels.at(-2) ?? "";
  const keep = /^[a-z]{2}$/.test(last) && /^[a-z]{2,3}$/.test(second) && labels.length > 2 ? 3 : 2;
  return labels.slice(-keep).join(".");
}
