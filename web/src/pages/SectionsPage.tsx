import { useEffect, useState } from "react";
import type { Section } from "../data/types";

export default function SectionsPage() {
  const [sections, setSections] = useState<Section[] | null>(null);

  useEffect(() => {
    fetch("/data/sections-index.json")
      .then((r) => r.json())
      .then(setSections);
  }, []);

  return (
    <div className="page">
      <h1 className="page__title">Разделы</h1>
      <p className="page__lede">
        Двенадцать разделов анамнеза — от психологического профиля до дневников
        и внешних источников. Число файлов — живой скан диска при каждом
        запуске, не зафиксированная цифра.
      </p>
      {!sections && <p>Загрузка…</p>}
      <div className="section-grid">
        {sections?.map((s) => (
          <a key={s.dir} className="section-card" href={`#/section/${s.dir}`}>
            <span className="section-card__title">{s.title}</span>
            <span className="section-card__desc">{s.desc}</span>
            <span className="section-card__count">{s.fileCount} файлов</span>
          </a>
        ))}
      </div>
    </div>
  );
}
