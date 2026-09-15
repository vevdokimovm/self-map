# Генерация изображений на MacBook Pro 13" 2018 (Intel i5-8259U, 8 ГБ) — что реально работает

**Дата:** 14.09.2026 · **Заказ владельца:** *«давай все же решим вопрос с изображением
для моего мака. по любому есть способ их генерить. сделай ресерч или что и репорт в конце»*.

Метки: **[офиц.]** — официальная документация, репозиторий, PyPI; **[форум]** — issues,
агрегаторы, блоги; **[оценка]** — расчёт, не замер.

> 🔴 **ПОПРАВКА ЗАМЕРОМ 15.09.2026.** Путь 3 проверен запуском на этом маке:
> stable-diffusion.cpp (сборка CPU, `-DGGML_METAL=OFF`) + SD-Turbo q8 + TAESD —
> **133 с** на 512×512 (оценка отчёта «10–30 с» занижена в 4–8 раз), качество —
> **годная иллюстрация**, а не «набросок». Metal на Iris Plus 655 падает по GPU Timeout.
> DiffusionBee 2.5.3 через brew установился. Итог: `15-image-kit/README.md` §0в.

## 1. Прямой ответ

**Хорошего локального пути на этом маке нет.** Почти все удобные мак-приложения и Core ML —
только Apple Silicon, а Python-стек бросил Intel Mac: **PyTorch** не собирается под
macOS x86_64 после **2.2.2**, **OpenVINO** на PyPI — после **2025.4.1**, **onnxruntime** —
после **1.23.2** (проверено PyPI JSON 14.09.2026).

Рабочих путей три:

1. **Gemini app в подписке Google AI Pro, руками** — лучшее качество, уже оплачено;
   из терминала не управляется. **Основной путь** — зашит в `/image` (набросок + промпт).
2. **Cloudflare Workers AI (FLUX.1 schnell) через `curl`** — бесплатно 10 000 нейронов
   в день (≈ 55–170 картинок [оценка]), работает из терминала. Из России нужен VPN.
3. **Локально на CPU** — stable-diffusion.cpp из исходников или FastSD CPU **старого
   релиза**; SD-Turbo / SD 1.5 + LCM, десятки секунд на 512px [оценка], качество заметно ниже.

🔴 **Находка сверх ожиданий.** README FastSD CPU пишет, что OpenVINO на Intel Mac работает,
но текущий `install-mac.sh` ставит `torch==2.8.0`, а `requirements.txt` — `openvino==2026.2.0`;
колёс macOS x86_64 нет ни для той, ни для другой версии. **Текущий инсталлятор на этом маке
упадёт.** README устарел.

## 2. Приложения с GUI

| Приложение | Intel Mac | Детали | Проверка |
|---|---|---|---|
| DiffusionBee | формально да | последний релиз 2.5.3 (14.08.2024), есть `DiffusionBee_MPS_Intel-2.5.3.dmg`; скорость на Iris Plus 655 не описана, ожидается очень медленно | [офиц.] [репо](https://github.com/divamgupta/diffusionbee-stable-diffusion-ui) |
| Draw Things | неясно | Intel experimental с 2023 («while slow»); без Metal FlashAttention «far slower»; с 1.09.2026 App Store разрешает убирать Intel | [офиц.] [App Store](https://apps.apple.com/us/app/draw-things-offline-ai-art/id6444050820); [форум] [MacRumors](https://www.macrumors.com/2026/09/01/mac-app-store-intel-mac-support/) |
| Mochi Diffusion | 🔴 нет | Apple Silicon only, macOS 15.6+ | [офиц.] [репо](https://github.com/godly-devotion/MochiDiffusion) |
| Amazing AI | 🔴 нет | «NOT compatible with Intel», macOS 15+ | [офиц.] [сайт](https://sindresorhus.com/amazing-ai) |
| apple/ml-stable-diffusion (Core ML) | 🔴 нет | target «Mac: M1» | [офиц.] [репо](https://github.com/apple/ml-stable-diffusion) |
| ComfyUI Desktop | 🔴 нет | ручная установка — только `--cpu`, минуты на картинку | [форум] |
| PyTorch MPS | 🔴 нет | Apple: «Mac computer with Apple silicon» | [офиц.] [Apple](https://developer.apple.com/metal/pytorch/) |

## 3. Консольные движки на CPU

### Корневое ограничение — колёса PyPI [офиц.]

| Пакет | Последняя с macOS x86_64 | Новее |
|---|---|---|
| torch | **2.2.2** | только arm64 |
| openvino | **2025.4.1** | только arm64 |
| onnxruntime | **1.23.2** | только arm64 |

Источники: [PyTorch dev-discuss](https://dev-discuss.pytorch.org/t/pytorch-macos-x86-builds-deprecation-starting-january-2024/1690),
[OpenVINO release notes](https://docs.openvino.ai/2025/about-openvino/release-notes-openvino.html).

### FastSD CPU (rupeshs/fastsdcpu)

- Бенчмарки README [офиц.] на Core i7-12700, 512×512, 1 шаг: SD-Turbo 7.8 с (PyTorch) /
  5 с (OpenVINO) / **1.7 с** (OpenVINO + TAESD); SDXS-512 — 0.82 с.
- RAM [офиц.]: LCM — 2 ГБ, LCM-LoRA — 4 ГБ, OpenVINO — 9–11 ГБ → на 8 ГБ своп, вредно
  изношенному SSD.
- Рабочий релиз для Intel — `v1.0.0-beta.200` (20.04.2025): `openvino==2024.4.0`,
  `onnxruntime==1.17.3`, torch не пинит → 2.2.2. Риск: `numpy<2`. **Запуском не проверено.**
- Есть CLI, REST API и MCP-сервер (`--mcp`) — Claude Code может звать генерацию сам.
- На i5-8259U [оценка]: SD-Turbo LCM ≈ 25–40 с на 512px; SD 1.5 + LCM-LoRA ≈ 1 мин.

### stable-diffusion.cpp (leejet)

- Бэкенды CPU (AVX2), Metal, Vulkan; GGUF-квантование, TAESD [офиц.] ([репо](https://github.com/leejet/stable-diffusion.cpp)).
- Готовые macOS-сборки — только arm64; на Intel — сборка из исходников (`cmake`).
- Metal по собственной доке «highly inefficient» — рассчитывать на CPU.
- Один бинарник без Python — устаревание колёс PyPI его не касается.
- Скорость на похожем CPU публично не замерена; [оценка] SD-Turbo q8, 1 шаг, 512px ≈ 10–30 с.

### Модели для 8 ГБ [оценка]

SD-Turbo, SDXS-512, SD 1.5 + LCM — реально · SDXL-Turbo — на грани · FLUX schnell GGUF q4 —
запустится, но непрактично медленно.

## 4. Облачные пути

| Путь | Бесплатно | Из терминала | Россия | Проверка |
|---|---|---|---|---|
| **Gemini app (AI Pro)** | да, в подписке (Nano Banana 2 / Pro) | нет | VPN | [офиц.] [справка](https://support.google.com/gemini/answer/14286560?hl=en); лимит официально «4x higher than standard» ([лимиты](https://support.google.com/gemini/answer/16275805?hl=en)), «100/день» — только агрегатор |
| **Gemini API** | 🔴 **нет** — у всех image-моделей Free Tier «Not available», от $0.0336 | да | регион не поддержан, VPN + иностранная карта | [офиц.] [pricing](https://ai.google.dev/gemini-api/docs/pricing), [регионы](https://ai.google.dev/gemini-api/docs/available-regions) |
| **Gemini CLI + nanobanana** | 🔴 нет — нужен API-ключ, подписка не подхватывается | да | как API | [офиц.] [README](https://github.com/gemini-cli-extensions/nanobanana), issue [#10781](https://github.com/google-gemini/gemini-cli/issues/10781) |
| **Cloudflare Workers AI** | 🟢 **да**, 10 000 нейронов/день; FLUX.1 schnell | да, `curl` | throttling Cloudflare с 06.2025 → VPN | [офиц.] [pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/), [модель](https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/) |
| Hugging Face Inference | $0.10/мес Free | да | не проверено | [офиц.] [pricing](https://huggingface.co/docs/inference-providers/pricing) |
| Pollinations.ai | неясно — источники противоречат | да | не проверено | — |
| Colab / Kaggle | GPU не гарантирован; Kaggle — проблемы с российскими номерами | ноутбук | — | [форум] |

## 5. Рекомендация для этого мака

1. **Gemini app — основной путь** (уже в `/image`): качество, текст на картинке, оплачено.
2. **Cloudflare Workers AI — если нужна автоматизация без денег.** Регистрация через VPN,
   `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` в `.env`:
   ```bash
   curl -s https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/run/@cf/black-forest-labs/flux-1-schnell \
     -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
     -d '{"prompt":"fjord at dawn, photo, no text","steps":4}' \
     | python3 -c "import sys,json,base64;open('out.jpg','wb').write(base64.b64decode(json.load(sys.stdin)['result']['image']))"
   ```
   Поле `result.image` — по доке, живым запросом не проверено.
3. **Локально офлайн — только ради независимости от сети:** stable-diffusion.cpp с SD-Turbo
   (сборка `cmake`) или FastSD CPU **с тегом `v1.0.0-beta.200`**, режим LCM, не OpenVINO.
   Качество — «иллюстрация/набросок», фотореализм слабый.

### 🔴 На Intel Mac НЕ работает

Mochi Diffusion · Amazing AI · Core ML Stable Diffusion · ComfyUI Desktop · PyTorch > 2.2.2 ·
OpenVINO 2026.x · onnxruntime > 1.23.2 · текущий `main` FastSD CPU · готовые сборки
stable-diffusion.cpp · PyTorch MPS на Iris Plus · FLUX через OpenVINO (~30 ГБ RAM).

## 6. Противоречия и как разрешены

1. README FastSD «OpenVINO работает на Intel» против пинов в `main` → прав PyPI.
2. Агрегаторы «до 500 бесплатных картинок в Gemini API» против официального pricing → прав официальный.
3. OpenVINO «no longer supported» при колёсах x86_64 до 2025.4.1 → колёса есть, валидации нет.
4. Pollinations: анонимный доступ против ключей «Pollen» → **не разрешено**.

## 7. Как это исследовалось

Агент-исследователь, breadth-first по четырём блокам без субагентов: ~14 WebSearch,
~14 WebFetch, ~20 запросов `curl` к PyPI JSON, GitHub API и сырым README. Противоречия
разрешались прямой проверкой колёс PyPI. Сверено с базой: путь «промпт → Gemini» уже
в `.claude/skills/image/SKILL.md`. Ничего не устанавливалось и не запускалось.
Расход агента: 124 889 токенов, 58 вызовов, 22 мин 41 с.

## 8. Что осталось неизвестным

- реальные секунды на картинку на i5-8259U для stable-diffusion.cpp и FastSD — только оценки;
- точный дневной лимит картинок Gemini app в AI Pro — официально лишь «4x standard»;
- требования Odyssey; работают ли Sana и PixArt на CPU Intel Mac;
- нужна ли карта для бесплатного Cloudflare Workers AI; текущие условия Pollinations;
- ограничения скачивания моделей с Hugging Face из России.
