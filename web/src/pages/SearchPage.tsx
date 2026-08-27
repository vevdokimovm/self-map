import { useEffect, useMemo, useState } from "react";
import type { Section } from "../data/types";

interface FlatFile {
  name: string;
  sectionTitle: string;
  sectionDir: string;
}

export default function SearchPage() {
  const [sections, setSections] = useState<Section[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetch("/data/sections-index.json")
      .then((r) => r.json())
      .then(setSections);
  }, []);

  const allFiles = useMemo<FlatFile[]>(() => {
    if (!sections) return [];
    const out: FlatFile[] = [];
    for (const s of sections) {
      for (const e of s.entries) {
        if (e.kind === "file") out.push({ name: e.name, sectionTitle: s.title, sectionDir: s.dir });
      }
    }
    return out;
  }, [sections]);

  const filtered = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return allFiles.filter((f) => f.name.toLowerCase().includes(q)).slice(0, 200);
  }, [allFiles, query]);

  return (
    <div className="page">
      <h1 className="page__title">Поиск по названиям файлов</h1>
      <p className="page__lede">
        Поиск по именам файлов внутри разделов верхнего уровня — не по
        содержимому документов (полнотекстовый поиск за пределами MVP).
      </p>
      <input
        className="search-input"
        placeholder="Начните вводить часть названия файла…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        autoFocus
      />
      {!sections && <p>Загрузка…</p>}
      {query.trim() && (
        <p className="page__lede">
          Найдено: {filtered.length}
          {filtered.length === 200 ? " (показаны первые 200)" : ""}
        </p>
      )}
      <div className="file-list">
        {filtered.map((f, i) => (
          <div key={i} className="file-row">
            <span>{f.name}</span>
            <span className="file-row__section">{f.sectionTitle}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
