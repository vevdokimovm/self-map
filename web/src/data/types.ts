export interface SectionEntry {
  name: string;
  kind: "file" | "dir";
  count?: number;
}

export interface Section {
  dir: string;
  title: string;
  desc: string;
  fileCount: number;
  entries: SectionEntry[];
}

export interface RegistryEntry {
  heading: string;
  status: string | null;
  bodyText: string;
}

export interface RegistryTopSection {
  title: string;
  entries: RegistryEntry[];
}

export interface Registry {
  sourceExists: boolean;
  sourceRelPath?: string;
  sections: RegistryTopSection[];
}
