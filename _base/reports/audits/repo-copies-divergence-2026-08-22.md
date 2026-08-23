# Карта расхождений копий реп — 22.08.2026

> Построено командой, ничего не перемещено и не удалено. Сравниваются две площадки:
> `~/Documents/<репа>` (A) и `~/Documents/система_репозиториев/<репа>` (B).
> `_base/` и `.git/` из сравнения исключены по построению.

## Сводка

| Репа | только A | только B | различаются | идентичны | вердикт |
|---|---:|---:|---:|---:|---|
| `ai-relay` | 0 | 0 | 0 | 6 | 🟢 копии идентичны — переезд безопасен |
| `visual-style` | 0 | 0 | 0 | 6 | 🟢 копии идентичны — переезд безопасен |
| `mission-control` | 1 | 0 | 4 | 98 | 🔴 разошлись в обе стороны |
| `dota-dossier` | 9 | 0 | 2 | 5146 | 🔴 разошлись в обе стороны |
| `character-a-analysis` | 0 | 0 | 0 | 336 | 🟢 копии идентичны — переезд безопасен |
| `portrait-of-taste` | 0 | 0 | 0 | 1571 | 🟢 копии идентичны — переезд безопасен |
| `base-repo` | 132 | 3 | 60 | 232 | 🔴 разошлись в обе стороны |

---

---

## `ai-relay`  ·  A v0.1.0 · B v0.1.0

**🟢 копии идентичны — переезд безопасен**

| | Файлов |
|---|---:|
| только в `~/Documents/ai-relay` (A) | **0** |
| только в `система_репозиториев/ai-relay` (B) | **0** |
| есть в обеих, **содержимое различается** | **0** |
| идентичны байт-в-байт | 6 |

---

## `visual-style`  ·  A v0.1.0 · B v0.1.0

**🟢 копии идентичны — переезд безопасен**

| | Файлов |
|---|---:|
| только в `~/Documents/visual-style` (A) | **0** |
| только в `система_репозиториев/visual-style` (B) | **0** |
| есть в обеих, **содержимое различается** | **0** |
| идентичны байт-в-байт | 6 |

---

## `mission-control`  ·  A v1.12.0 · B v1.12.0

**🔴 разошлись в обе стороны**

| | Файлов |
|---|---:|
| только в `~/Documents/mission-control` (A) | **1** |
| только в `система_репозиториев/mission-control` (B) | **0** |
| есть в обеих, **содержимое различается** | **4** |
| идентичны байт-в-байт | 98 |

**Только в A (~/Documents/mission-control):**

- `.claude/scheduled_tasks.lock`

**Различаются по содержимому:**

- `BOARD.md`
- `scripts/deploy.sh`
- `scripts/push-inbox-history.log`
- `scripts/push-inbox.sh`

---

## `dota-dossier`  ·  A v2.42.0 · B v2.42.0

**🔴 разошлись в обе стороны**

| | Файлов |
|---|---:|
| только в `~/Documents/dota-dossier` (A) | **9** |
| только в `система_репозиториев/dota-dossier` (B) | **0** |
| есть в обеих, **содержимое различается** | **2** |
| идентичны байт-в-байт | 5146 |

**Только в A (~/Documents/dota-dossier):**

- `src/__pycache__/__init__.cpython-314.pyc`
- `src/__pycache__/coach_advisor.cpython-314.pyc`
- `src/__pycache__/hero_build_research.cpython-310.pyc`
- `src/__pycache__/hero_data_sheet.cpython-310.pyc`
- `src/__pycache__/meta_tiers.cpython-314.pyc`
- `src/__pycache__/render_ai_report.cpython-314.pyc`
- `src/__pycache__/render_picks.cpython-314.pyc`
- `src/__pycache__/ti2026_forecast.cpython-314.pyc`
- `src/__pycache__/ti2026_playoff_model.cpython-314.pyc`

**Различаются по содержимому:**

- `data/dota_export_1710957099/match_index.csv`
- `docs/items/gem/overview.md`

---

## `character-a-analysis`  ·  A v3.45.1 · B v3.45.1

**🟢 копии идентичны — переезд безопасен**

| | Файлов |
|---|---:|
| только в `~/Documents/character-a-analysis` (A) | **0** |
| только в `система_репозиториев/character-a-analysis` (B) | **0** |
| есть в обеих, **содержимое различается** | **0** |
| идентичны байт-в-байт | 336 |

---

## `portrait-of-taste`  ·  A v3.6.14 · B v3.6.14

**🟢 копии идентичны — переезд безопасен**

| | Файлов |
|---|---:|
| только в `~/Documents/portrait-of-taste` (A) | **0** |
| только в `система_репозиториев/portrait-of-taste` (B) | **0** |
| есть в обеих, **содержимое различается** | **0** |
| идентичны байт-в-байт | 1571 |

---

## `base-repo`  ·  A v2.37.0 · B v1.42.0

**🔴 разошлись в обе стороны**

| | Файлов |
|---|---:|
| только в `~/Documents/base-repo` (A) | **132** |
| только в `система_репозиториев/base-repo` (B) | **3** |
| есть в обеих, **содержимое различается** | **60** |
| идентичны байт-в-байт | 232 |

**Только в A (~/Documents/base-repo):**

- `.claude/agents/base-coverage-probe.md`
- `.claude/agents/repo-inventory.md`
- `.claude/agents/token-probe.md`
- `.claude/hooks/ritual-gate.sh`
- `.claude/scheduled_tasks.lock`
- `.claude/settings.json`
- `.claude/settings.local.json`
- `.claude/skills/auto/SKILL.md`
- `.claude/skills/handoff/SKILL.md`
- `.claude/skills/handoff/evals/evals.json`
- `.claude/skills/tokens/SKILL.md`
- `.repo-class`
- `00-infrastructure/49-token-economy-and-prompting.md`
- `00-infrastructure/50-parallel-accounts-and-admin-orchestration.md`
- `00-infrastructure/51-autonomous-agent-loop.md`
- `00-infrastructure/52-hardware-baseline.md`
- `00-infrastructure/53-infrastructure-sync-standard.md`
- `00-infrastructure/54-pdf-reading-channels.md`
- `00-infrastructure/55-pdf-channels-experiment.md`
- `00-infrastructure/56-chat-to-project-to-repo.md`
- `00-infrastructure/57-self-sufficiency-rule.md`
- `00-infrastructure/58-git-practice.md`
- `00-infrastructure/59-public-mirror-filter.md`
- `00-infrastructure/60-audio-video-pipeline.md`
- `00-infrastructure/61-token-analytics.md`
- `00-infrastructure/62-vim.md`
- `00-infrastructure/63-ai-tools-landscape.md`
- `00-infrastructure/64-claude-code-sandbox.md`
- `00-infrastructure/65-visual-source-pipeline.md`
- `00-infrastructure/66-model-and-effort-selection.md`
- `00-infrastructure/67-information-compression.md`
- `00-infrastructure/68-writing-guides.md`
- `00-infrastructure/69-agents-hooks-and-gates.md`
- `00-infrastructure/70-independent-review-blindness.md`
- `00-infrastructure/71-fail-loud-and-sourcing.md`
- `00-infrastructure/72-source-of-truth.md`
- `00-infrastructure/73-chat-handoff.md`
- `00-infrastructure/74-planner-bridge.md`
- `00-infrastructure/75-readme-status-block.md`
- `00-infrastructure/76-repo-classes.md`
- … ещё 92

**Только в B (система_репозиториев):**

- `00-infrastructure/00-navigator.md`
- `00-infrastructure/base-repo-readme.md`
- `00-infrastructure/repo-readme-template.md`

**Различаются по содержимому:**

- `.githooks/pre-commit`
- `00-CLAUDE-STOP.md`
- `00-infrastructure/01-repo-standard.md`
- `00-infrastructure/04-watchlog-protocol.md`
- `00-infrastructure/07-writing-methodology.md`
- `00-infrastructure/08-automation-triggers.md`
- `00-infrastructure/16-limits-empirical-estimate.md`
- `00-infrastructure/18-documentation-philosophy.md`
- `00-infrastructure/19-reporting-system.md`
- `00-infrastructure/20-knowledge-capture-protocol.md`
- `00-infrastructure/21-revision-protocol.md`
- `00-infrastructure/22-merge-protocol.md`
- `00-infrastructure/23-session-continuity.md`
- `00-infrastructure/24-changelog-protocol.md`
- `00-infrastructure/25-versioning-and-releases.md`
- `00-infrastructure/28-empirical-experiment-methodology.md`
- `00-infrastructure/32-git-hooks-and-secret-scanning.md`
- `00-infrastructure/33-token-budget-and-modes.md`
- `00-infrastructure/34-cowork-scheduled-tasks.md`
- `00-infrastructure/37-skills-system.md`
- `00-infrastructure/40-tools-and-capabilities-map.md`
- `00-infrastructure/41-playbook-make-tasks-and-plugins.md`
- `00-infrastructure/42-release-description-standard.md`
- `00-infrastructure/43-archive-naming-and-packaging.md`
- `00-infrastructure/44-what-to-version.md`
- `00-infrastructure/45-roadmap-and-tasks.md`
- `00-infrastructure/47-roles.md`
- `00-infrastructure/README.md`
- `00-infrastructure/WATCHLOG.md`
- `00-infrastructure/incident-postmortem-guide.md`
- `02-methodology-library/cybersecurity_methodology.md`
- `CHANGELOG.md`
- `README.md`
- `START-HERE.md`
- `VERSION`
- `reports/README.md`
- `reports/adr/README.md`
- `reports/experiments/token-consumption/README.md`
- `reports/experiments/token-consumption/hypothesis.md`
- `reports/experiments/token-consumption/measurements.csv`
- … ещё 20

---
