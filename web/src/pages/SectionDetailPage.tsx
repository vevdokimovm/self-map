import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import type { Section, SectionEntry } from "../data/types";

// Показывает только имена файлов/подпапок раздела — не содержимое.
// Полный текст открывается только вручную, вне этого приложения (Finder/редактор),
// намеренно: это инструмент навигации, не витрина чувствительного контента.
function flatten(entries: SectionEntry[], prefix: string): { name: string; path: string }[] {
  const out: { name: string; path: string }[] = [];
  for (const e of entries) {
    const path = prefix ? `${prefix}/${e.name}` : e.name;
    if (e.kind === "file") out.push({ name: e.name, path });
  }
  return out;
}

export default function SectionDetailPage() {
  const { dir } = useParams<{ dir: string }>();
  const [section, setSection] = useState<Section | null>(null);

  useEffect(() => {
    fetch("/data/sections-index.json")
      .then((r) => r.json())
      .then((all: Section[]) => setSection(all.find((s) => s.dir === dir) ?? null));
  }, [dir]);

  if (!section) return <div className="page">Загрузка…</div>;

  const files = flatten(section.entries, "");

  return (
    <div className="page">
      <p>
        <Link to="/" className="source-link">
          ← Разделы
        </Link>
      </p>
      <h1 className="page__title">{section.title}</h1>
      <p className="page__lede">
        {section.desc} · {section.fileCount} файлов в {`${section.dir}/`}
      </p>
      <div className="notice">
        Список — только имена файлов. Полное содержимое открывается вне
        приложения (в файловой системе), чтобы чувствительные материалы не
        всплывали превью на экране случайно.
      </div>
      <div className="file-list">
        {files.map((f) => (
          <div key={f.path} className="file-row">
            <span>{f.name}</span>
          </div>
        ))}
        {section.entries
          .filter((e) => e.kind === "dir")
          .map((d) => (
            <div key={d.name} className="file-row">
              <span>{d.name}/</span>
              <span className="file-row__section">{d.count} файлов</span>
            </div>
          ))}
      </div>
    </div>
  );
}
