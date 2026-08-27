import { useEffect, useState } from "react";
import type { Registry, RegistryEntry } from "../data/types";

const STATUS_LABEL: Record<string, string> = {
  "✅": "подтверждено",
  "🔴": "флаг/новое",
  "🔴🔴": "флаг/ломает прежнюю картину",
  "🟢": "починено/ок",
  "🔬": "методологическая заметка",
  "⏳": "не разобрано",
};

function EntryRow({ entry }: { entry: RegistryEntry }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="registry-entry">
      <div className="registry-entry__head" onClick={() => setOpen((v) => !v)}>
        {entry.status && (
          <span className="registry-entry__status" title={STATUS_LABEL[entry.status] ?? entry.status}>
            {entry.status}
          </span>
        )}
        <span className="registry-entry__heading">{entry.heading}</span>
      </div>
      {open && <div className="registry-entry__body">{entry.bodyText}</div>}
    </div>
  );
}

export default function RegistryPage() {
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [activeTab, setActiveTab] = useState<number>(0);

  useEffect(() => {
    fetch("/data/registry.json")
      .then((r) => r.json())
      .then(setRegistry);
  }, []);

  if (!registry) return <div className="page">Загрузка…</div>;

  if (!registry.sourceExists) {
    return (
      <div className="page">
        <h1 className="page__title">Реестр фактов</h1>
        <div className="notice">
          Файл реестра не найден на диске — раздел неактуален для текущего
          состояния репозитория.
        </div>
      </div>
    );
  }

  const active = registry.sections[activeTab];

  return (
    <div className="page">
      <h1 className="page__title">Реестр фактов и гипотез</h1>
      <p className="page__lede">
        Порядок записей — порядок исходного документа, не календарная
        хронология: в заголовках нет надёжно единообразных дат для
        автоматической сортировки по времени, и придумывать даты значило бы
        исказить источник. Статус-эмодзи — эвристика (первый статус-глиф,
        найденный в записи), не строго формальное поле файла.
      </p>
      <p style={{ marginBottom: "var(--sp-4)" }}>
        <span className="source-link">Источник: {registry.sourceRelPath}</span>
      </p>
      <div className="registry-tabs">
        {registry.sections.map((s, i) => (
          <button
            key={s.title}
            className={i === activeTab ? "registry-tab active" : "registry-tab"}
            onClick={() => setActiveTab(i)}
          >
            {s.title} ({s.entries.length})
          </button>
        ))}
      </div>
      {active.entries.length === 0 && <p className="page__lede">В этой секции записей не распознано.</p>}
      {active.entries.map((e, i) => (
        <EntryRow key={i} entry={e} />
      ))}
    </div>
  );
}
