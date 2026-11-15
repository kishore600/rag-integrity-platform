/**
 * The user guide, read straight from docs/user-guide at build time: the written guide and the Help pages are one source, so they
 * cannot disagree. Chapters load on demand (each is its own chunk); screenshots are emitted as hashed assets by the build.
 */
const sources = import.meta.glob<string>("../../../../docs/user-guide/*.md", { query: "?raw", import: "default" });
const images = import.meta.glob<string>("../../../../docs/user-guide/images/*.png", { query: "?url", import: "default", eager: true });

const fileName = (path: string) => path.replace(/^.*\//, "");
const stem = (path: string) => fileName(path).replace(/\.[^.]+$/, "");

const loaders = new Map(Object.entries(sources).map(([path, load]) => [stem(path), load]));
const imageByName = new Map(Object.entries(images).map(([path, url]) => [fileName(path), url]));

export interface Chapter {
  slug: string;
  number: string;
  title: string;
  summary: string;
}
export interface ChapterGroup {
  title: string;
  chapters: Chapter[];
}

/** A chapter is any numbered file in the guide folder. The README is the contents page, not a chapter. */
export const hasChapter = (slug: string): boolean => slug !== "README" && loaders.has(slug);

export function loadMarkdown(slug: string): Promise<string> {
  const load = loaders.get(slug);
  return load ? load() : Promise.reject(new Error(`There is no chapter called "${slug}".`));
}

/** The URL of a screenshot, by the file name used in the Markdown (images/login.png -> login.png). */
export const imageUrl = (file: string): string | undefined => imageByName.get(fileName(file));

// | [7. Integrity issues](07-integrity-issues.md) | Filtering and reading issues ... |
const ROW = /^\|\s*\[(\d+)\.\s+([^\]]+)\]\(([\w-]+)\.md\)\s*\|\s*(.*?)\s*\|\s*$/;

/** The contents page: the chapters of README.md in its own order and groups ("Set up", "The pages", "Putting it to work"). */
export function parseIndex(readme: string): ChapterGroup[] {
  const groups: ChapterGroup[] = [];
  for (const line of readme.split(/\r?\n/)) {
    const heading = /^###\s+(.+?)\s*$/.exec(line);
    if (heading) {
      groups.push({ title: heading[1], chapters: [] });
      continue;
    }
    const row = ROW.exec(line);
    if (row && groups.length) groups[groups.length - 1].chapters.push({ slug: row[3], number: row[1], title: row[2], summary: row[4].replace(/\*\*/g, "") });
  }
  return groups.filter((g) => g.chapters.length > 0);
}

export const loadIndex = async (): Promise<ChapterGroup[]> => parseIndex(await loadMarkdown("README"));

export { MEDIA } from "@/lib/help-media";
