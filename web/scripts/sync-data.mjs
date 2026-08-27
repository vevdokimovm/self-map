// Строит public/data/*.json из репозитория (единственный источник правды).
// Ничего не пишет обратно в источник, ничего не отправляет по сети — только
// читает локальные файлы и кладёт в public/data, откуда фронт берёт их через
// fetch(). Счётчики файлов по разделам всегда живой скан диска, никогда не
// хардкод — иначе цифры молча устаревают (см. family/web/scripts/sync-data.mjs,
// тот же паттерн).
import { mkdirSync, existsSync, writeFileSync, readdirSync, statSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "..");
const repoRoot = join(webRoot, "..");
const outDir = join(webRoot, "public", "data");
mkdirSync(outDir, { recursive: true });

// --- 1. Разделы: живой скан, описания — с формулировками из MANIFEST.md §3 ---

const SECTIONS = [
  { dir: "01-psychological-profile", title: "Психологический профиль", desc: "Профиль, тень, подличности (IFS), портрет" },
  { dir: "02-clinical", title: "Клиническое", desc: "Терапевтическая карта, MMPI, «Мне бывает больно»" },
  { dir: "03-competency-reports-rsv", title: "Компетентностные отчёты", desc: "Отчёты РЦВ: ценности, жизнестойкость, клиентоориентированность" },
  { dir: "04-genetics-genotek", title: "Генетика (личность)", desc: "Генетика в части личности — не медицина (см. health-vault)" },
  { dir: "05-faith", title: "Вера", desc: "Вера только как черта личности — не богословие (см. christ-walk)" },
  { dir: "06-diaries", title: "Дневники", desc: "Дневники, включая материальный дневник по частям" },
  { dir: "07-self-reflection", title: "Саморефлексия", desc: "«Книга возвращения к себе», аксиоматика мировоззрения" },
  { dir: "08-feedback", title: "Обратная связь", desc: "Обратная связь от других людей о владельце" },
  { dir: "09-session-summaries", title: "Итоги сессий", desc: "Сводки психологических сессий" },
  { dir: "10-life-history", title: "История жизни", desc: "История жизни по периодам, реестр фактов и гипотез" },
  { dir: "11-external-sources", title: "Внешние источники", desc: "Telegram-канал «МОЗГ.ПСИХОЛОГИЯ» и другие внешние материалы" },
  { dir: "99-misc", title: "Разное", desc: "To-do и неразложенное" },
];

const IGNORE = new Set([".DS_Store", "_base", "_knowledge-kit", "raspoznavanie.md"]);

function countFiles(dir) {
  let count = 0;
  let items = [];
  try { items = readdirSync(dir); } catch { return { count: 0, entries: [] }; }
  const entries = [];
  for (const name of items) {
    if (IGNORE.has(name)) continue;
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      const sub = countFiles(full);
      count += sub.count;
      entries.push({ name, kind: "dir", count: sub.count });
    } else {
      count += 1;
      entries.push({ name, kind: "file" });
    }
  }
  return { count, entries };
}

const sectionsIndex = SECTIONS.map((s) => {
  const { count, entries } = countFiles(join(repoRoot, s.dir));
  return { ...s, fileCount: count, entries };
});

writeFileSync(join(outDir, "sections-index.json"), JSON.stringify(sectionsIndex, null, 2));
console.log(`[sync-data] sections-index.json — ${sectionsIndex.reduce((a, s) => a + s.fileCount, 0)} файлов проиндексировано`);

// --- 2. Реестр фактов и гипотез: парсинг facts-and-hypotheses.md -------------
//
// Формат файла не строго регулярен (эмодзи-статусы разные, не всегда есть дата
// в заголовке) — поэтому парсер извлекает только то, что действительно
// надёжно извлекается: номер, заголовок, статус-эмодзи, секцию верхнего
// уровня (§1 факты / §2 гипотезы) и тело записи целиком (дословно, без
// перефразирования). Порядок — порядок документа, НЕ календарная сортировка:
// в заголовках нет надёжно единообразных дат для автоматической хронологии,
// и придумывать даты там, где их нет, значило бы исказить факты. Полный текст
// исходника остаётся источником правды — реестр это витрина по нему, не замена.

const registryPath = join(repoRoot, "10-life-history", "01-registry", "facts-and-hypotheses.md");
let registry = { sourceExists: false, sections: [] };

if (existsSync(registryPath)) {
  const text = readFileSync(registryPath, "utf-8");
  const lines = text.split("\n");

  let currentTopSection = null; // "§1. УСТАНОВЛЕННЫЕ ФАКТЫ" и т.п.
  let currentEntry = null;
  const topSections = [];

  const STATUS_RE = /(✅|🔴🔴|🔴|🟢|🔬|⏳)/;

  function pushEntry() {
    if (currentEntry && currentTopSection) {
      currentTopSection.entries.push(currentEntry);
    }
    currentEntry = null;
  }

  for (const line of lines) {
    const topMatch = line.match(/^#\s+(§\d+\..+)$/);
    const entryMatch = line.match(/^##\s+(.+)$/);

    if (topMatch) {
      pushEntry();
      currentTopSection = { title: topMatch[1].trim(), entries: [] };
      topSections.push(currentTopSection);
      continue;
    }

    if (entryMatch) {
      pushEntry();
      const heading = entryMatch[1].trim();
      currentEntry = {
        heading,
        status: null, // заполняется ниже по заголовку + телу целиком
        body: [],
      };
      continue;
    }

    if (currentEntry) {
      currentEntry.body.push(line);
    }
  }
  pushEntry();

  // тело — дословный текст, схлопнуть только окружающие пустые строки.
  // Статус — эвристика: первый статус-глиф, встреченный в заголовке ИЛИ
  // теле записи целиком (не строго формальное поле файла) — помечается в UI
  // как маркер-подсказка, не как гарантированный факт разбора.
  for (const sec of topSections) {
    for (const e of sec.entries) {
      while (e.body.length && e.body[0].trim() === "") e.body.shift();
      while (e.body.length && e.body[e.body.length - 1].trim() === "") e.body.pop();
      e.bodyText = e.body.join("\n");
      delete e.body;
      const haystack = e.heading + "\n" + e.bodyText;
      const statusMatch = haystack.match(STATUS_RE);
      e.status = statusMatch ? statusMatch[1] : null;
    }
  }

  registry = { sourceExists: true, sourceRelPath: "10-life-history/01-registry/facts-and-hypotheses.md", sections: topSections };
}

writeFileSync(join(outDir, "registry.json"), JSON.stringify(registry, null, 2));
const entryCount = registry.sections.reduce((a, s) => a + s.entries.length, 0);
console.log(`[sync-data] registry.json — ${registry.sections.length} секций, ${entryCount} записей распознано`);
