export const DOCUMENT_ACCEPT = ".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export function validateFiles(files: File[]): string | null {
  if (!files.length) return "Select at least one PDF or DOCX file";
  if (files.some((file) => !/\.(pdf|docx)$/i.test(file.name))) return "Only PDF and DOCX files are supported";
  if (files.some((file) => file.size === 0)) return "Empty files are not supported";
  if (files.length > 20 || files.reduce((sum, file) => sum + file.size, 0) > 32 * 1024 * 1024) return "Upload up to 20 files and 32 MiB at a time";
  return null;
}

export function mergeFiles(current: File[], incoming: File[]) {
  const signature = (file: File) => `${file.name}:${file.size}:${file.lastModified}:${file.type}`;
  const seen = new Set(current.map(signature));
  return [...current, ...incoming.filter((file) => {
    if (seen.has(signature(file))) return false;
    seen.add(signature(file));
    return true;
  })];
}

export function documentKey(uri: string): string | null {
  let value = uri.replace(/^evidence:\/\//, "").replace(/^\.\//, "");
  try { value = decodeURIComponent(value); } catch { return null; }
  return value.startsWith("documents/") && !value.split("/").includes("..") ? value : null;
}
