#!/usr/bin/env python3
"""firmware_probe.py — прошивка и базовое ПО на macOS, Linux и Windows.

🔴 ЗАКАЗ ВЛАДЕЛЬЦА 03.09.2026 22:15: *«сделай, чтобы когда я запускаю этот
скилл на других машинах, где другая ОС — Windows, Linux и т.д., — там всё это
считывалось. На эпл процессорах, на компах с блоками и т.д. Все данные BIOS,
железа и изначального самого фундаментального софта, связывающего машину,
софт и хард»*.

## 🔴 ГЛАВНОЕ ОГРАНИЧЕНИЕ, названное прежде возможностей

**Проверено вживую только на macOS Intel** (MacBookPro15,2, T2, macOS 15.7.7) —
другой машины у вахты нет. Ветки Linux, Windows и Apple Silicon написаны
по документированным источникам и проверены **на образцах вывода**, а не
на живых системах.

Это разные утверждения, и путать их нельзя (`71` §7г-бис). Что именно
проверено:

  · разбор текста — да, на зафиксированных образцах (`selftest`);
  · что команда существует и вернёт такой текст — **нет**, для Linux/Windows;
  · что источник верен для конкретного дистрибутива или сборки — **нет**.

Поэтому на неподдержанной или непроверенной платформе модуль **говорит об
этом в выводе**, а не молчит и не выдаёт догадку за замер. Первый же запуск
на живой Linux-машине либо подтвердит разбор, либо покажет, где он неверен, —
и тогда строка «проверено» здесь меняется на честную.

## Что считается «прошивкой» на каждой платформе

| | macOS Intel | macOS Apple Silicon | Linux | Windows |
|---|---|---|---|---|
| прошивка | EFI (`System Firmware Version`) | iBoot / System Firmware | BIOS/UEFI (DMI) | BIOS/UEFI (WMI) |
| чип доверия | Apple T2 | Secure Enclave (в SoC) | TPM 2.0 | TPM 2.0 |
| защита загрузки | Secure Boot (T2) | Secure Boot (iBoot) | Secure Boot (UEFI) | Secure Boot |
| шифрование диска | FileVault | FileVault | LUKS | BitLocker |
| защита системы | SIP | SIP | SELinux / AppArmor | — |

**Ключи словаря одни и те же на всех платформах** — иначе вызывающий код
пришлось бы ветвить, и ветвление расползлось бы по вызывающим (`PIT-097`:
свойство, а не список). Недоступное поле = `"недоступно"`, а не отсутствие
ключа: отсутствие ключа роняет вызывающего, «недоступно» — говорит правду.

## Почему разбор отделён от сбора

Каждая функция `parse_*` принимает **текст** и возвращает словарь. Сбор
(`_run`) отделён. Так разбор Linux и Windows проверяется на образцах вывода
прямо здесь, на macOS, — единственный доступный способ проверить хоть что-то
в коде для платформы, которой нет под рукой.

ЗАПУСК
    firmware_probe.py              снимок текущей машины
    firmware_probe.py --json
    firmware_probe.py --selftest   разбор всех трёх платформ на образцах
"""
from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Единая форма ответа. Любая ветка возвращает ЭТИ ключи и никакие другие.
KEYS = ("платформа", "ос", "ядро", "архитектура", "производитель", "модель",
        "материнская_плата", "прошивка_вендор", "прошивка_версия",
        "прошивка_дата", "чип_доверия", "secure_boot", "шифрование_диска",
        "защита_системы", "серийный", "проверено_вживую")

NA = "недоступно"


def _blank(platform_name: str) -> dict:
    d = {k: NA for k in KEYS}
    d["платформа"] = platform_name
    d["проверено_вживую"] = False
    return d


def _run(cmd: list[str], timeout: int = 20) -> str:
    """Выполнить и вернуть stdout. Отсутствие команды — пустая строка, не отказ.

    🔴 Пустая строка здесь законна и означает «не спросили». Отличать её от
    «спросили и получили пусто» вызывающему не нужно: обе ведут в `недоступно`,
    и это честно — мы действительно не знаем.
    """
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ============================================================== macOS ========
def parse_macos(hw: str, ibridge: str, sip: str, gate: str,
                vault: str, arch: str) -> dict:
    """Разбор вывода `system_profiler` и утилит защиты.

    Apple Silicon отличается от Intel по существу, а не по формату:
      · `Chip: Apple M2` вместо `Processor Name`;
      · **чипа T2 нет** — Secure Enclave встроен в SoC, `SPiBridgeDataType`
        пуст. Пустой раздел здесь означает «не отдельный чип», а не «отказ»;
      · Secure Boot всегда включён и не отключается штатно.
    """
    d = _blank("macOS")

    def grab(text: str, label: str) -> str:
        m = re.search(rf"{label}:\s*(.+)", text)
        return m.group(1).strip() if m else NA

    apple_silicon = arch.startswith("arm")
    d["ос"] = f"macOS {platform.mac_ver()[0]}"
    d["ядро"] = platform.release()
    d["архитектура"] = arch
    d["производитель"] = "Apple"
    d["модель"] = grab(hw, "Model Identifier")
    d["материнская_плата"] = "интегрирована (Apple)"
    d["прошивка_вендор"] = "Apple EFI" if not apple_silicon else "Apple iBoot"
    d["прошивка_версия"] = grab(hw, "System Firmware Version")
    d["прошивка_дата"] = NA          # Apple версию датой не сопровождает

    t2 = grab(ibridge, "Model Name")
    if t2 != NA:
        d["чип_доверия"] = f"{t2} · прошивка {grab(ibridge, 'Firmware Version')}"
    elif apple_silicon:
        # Не отказ: у Apple Silicon Secure Enclave внутри SoC, отдельного
        # чипа нет и быть не должно. Написать «недоступно» значило бы солгать.
        d["чип_доверия"] = "Secure Enclave (в составе SoC)"

    d["secure_boot"] = ("включён (Apple Silicon, штатно не отключается)"
                        if apple_silicon else
                        "задаётся в Recovery (bputil) — отсюда не читается")
    d["шифрование_диска"] = ("FileVault включён" if "FileVault is On" in vault
                             else "FileVault выключен" if vault else NA)
    d["защита_системы"] = ("SIP включён" if "enabled" in sip
                           else "SIP выключен" if sip else NA)
    if gate:
        d["защита_системы"] += (" · Gatekeeper включён"
                                if "assessments enabled" in gate
                                else " · Gatekeeper выключен")
    serial = grab(hw, r"Serial Number \(system\)")
    d["серийный"] = "…" + serial[-4:] if serial != NA and len(serial) > 4 else serial
    d["проверено_вживую"] = not apple_silicon    # Intel — да, Silicon — нет
    return d


# ============================================================== Linux ========
def parse_linux(dmi: dict, os_release: str, sb: str, luks: str,
                lsm: str, tpm: str) -> dict:
    """Разбор DMI и утилит Linux.

    🔴 ИСТОЧНИК ВЫБРАН БЕЗ ROOT. `dmidecode` даёт больше, но требует root;
    `/sys/class/dmi/id/*` читается обычным пользователем и содержит то же
    для наших полей. Инструмент осмотра, требующий root, не запустят —
    и он не покажет ничего вместо «покажет меньше».
    """
    d = _blank("Linux")
    d["ос"] = (re.search(r'^PRETTY_NAME="?([^"\n]+)"?', os_release, re.M).group(1)
               if re.search(r'^PRETTY_NAME=', os_release, re.M) else NA)
    d["ядро"] = platform.release()
    d["архитектура"] = platform.machine()
    d["производитель"] = dmi.get("sys_vendor", NA)
    d["модель"] = dmi.get("product_name", NA)
    board = dmi.get("board_name", NA)
    board_v = dmi.get("board_vendor", "")
    d["материнская_плата"] = f"{board_v} {board}".strip() if board != NA else NA
    d["прошивка_вендор"] = dmi.get("bios_vendor", NA)
    d["прошивка_версия"] = dmi.get("bios_version", NA)
    d["прошивка_дата"] = dmi.get("bios_date", NA)

    # TPM: наличие каталога уже ответ. Версия — в `tpm_version_major`.
    d["чип_доверия"] = f"TPM {tpm}" if tpm else NA

    if sb:
        low = sb.lower()
        d["secure_boot"] = ("включён" if "enabled" in low
                            else "выключен" if "disabled" in low else NA)

    # LUKS: `lsblk -o TYPE` содержит `crypt` у зашифрованных разделов.
    if luks:
        d["шифрование_диска"] = ("LUKS: есть зашифрованные разделы"
                                 if "crypt" in luks else "LUKS не найден")

    if lsm:
        low = lsm.lower()
        if "enforcing" in low:
            d["защита_системы"] = "SELinux: enforcing"
        elif "permissive" in low:
            d["защита_системы"] = "SELinux: permissive (не блокирует)"
        elif "apparmor" in low:
            d["защита_системы"] = "AppArmor активен"
    d["серийный"] = (lambda s: "…" + s[-4:] if s != NA and len(s) > 4 else s)(
        dmi.get("product_serial", NA))
    return d


# ============================================================ Windows ========
def parse_windows(bios: str, cs: str, board: str, sb: str,
                  bl: str, tpm: str, osver: str) -> dict:
    """Разбор вывода PowerShell/WMI.

    Поля берутся из `Get-CimInstance`: `Win32_BIOS`, `Win32_ComputerSystem`,
    `Win32_BaseBoard`, `Win32_OperatingSystem`. Формат — `Key : Value`,
    как печатает `Format-List`.

    🔴 `wmic` НЕ используется намеренно: он объявлен устаревшим и удалён
    из свежих сборок Windows 11. Инструмент, опирающийся на удаляемую
    команду, ломается молча в тот день, когда её уберут.
    """
    d = _blank("Windows")

    def grab(text: str, label: str) -> str:
        m = re.search(rf"^{label}\s*:\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else NA

    d["ос"] = grab(osver, "Caption")
    build = grab(osver, "BuildNumber")
    if d["ос"] != NA and build != NA:
        d["ос"] += f" (сборка {build})"
    d["ядро"] = platform.version()
    d["архитектура"] = platform.machine()
    d["производитель"] = grab(cs, "Manufacturer")
    d["модель"] = grab(cs, "Model")
    d["материнская_плата"] = f'{grab(board, "Manufacturer")} {grab(board, "Product")}'.strip()
    d["прошивка_вендор"] = grab(bios, "Manufacturer")
    d["прошивка_версия"] = grab(bios, "SMBIOSBIOSVersion")
    raw_date = grab(bios, "ReleaseDate")
    m = re.match(r"(\d{4})(\d{2})(\d{2})", raw_date)
    d["прошивка_дата"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else raw_date

    if tpm:
        present = "True" in tpm
        enabled = re.search(r"IsEnabled_InitialValue\s*:\s*True", tpm)
        d["чип_доверия"] = ("TPM присутствует" + (", включён" if enabled else "")
                            if present else "TPM не найден")
    if sb:
        d["secure_boot"] = ("включён" if "True" in sb
                            else "выключен" if "False" in sb else NA)
    if bl:
        d["шифрование_диска"] = ("BitLocker: защита включена"
                                 if "Protection On" in bl or "Защита включена" in bl
                                 else "BitLocker: защита выключена")
    d["защита_системы"] = NA          # прямого аналога SIP/SELinux нет
    serial = grab(bios, "SerialNumber")
    d["серийный"] = "…" + serial[-4:] if serial != NA and len(serial) > 4 else serial
    return d


# ============================================================== сбор ========
def collect() -> dict:
    """Снимок текущей машины. Ветвление по платформе — здесь и только здесь."""
    system = platform.system()

    if system == "Darwin":
        return parse_macos(
            _run(["system_profiler", "SPHardwareDataType"], 30),
            _run(["system_profiler", "SPiBridgeDataType"], 30),
            _run(["csrutil", "status"]),
            _run(["spctl", "--status"]),
            _run(["fdesetup", "status"]),
            platform.machine())

    if system == "Linux":
        dmi_dir = Path("/sys/class/dmi/id")
        dmi = {}
        if dmi_dir.is_dir():
            for f in dmi_dir.iterdir():
                try:
                    if f.is_file():
                        dmi[f.name] = f.read_text(errors="replace").strip()
                except OSError:
                    continue        # product_serial обычно требует root — норма
        tpm = ""
        tv = Path("/sys/class/tpm/tpm0/tpm_version_major")
        if tv.is_file():
            try:
                tpm = tv.read_text().strip()
            except OSError:
                tpm = ""
        elif Path("/sys/class/tpm/tpm0").exists():
            tpm = "?"
        osr = Path("/etc/os-release")
        d = parse_linux(
            dmi,
            osr.read_text(errors="replace") if osr.is_file() else "",
            _run(["mokutil", "--sb-state"]),
            _run(["lsblk", "-o", "TYPE"]),
            _run(["sestatus"]) or _run(["aa-status"]),
            tpm)
        return d

    if system == "Windows":
        def ps(expr: str) -> str:
            return _run(["powershell", "-NoProfile", "-Command", expr], 30)
        return parse_windows(
            ps("Get-CimInstance Win32_BIOS | Format-List *"),
            ps("Get-CimInstance Win32_ComputerSystem | Format-List *"),
            ps("Get-CimInstance Win32_BaseBoard | Format-List *"),
            ps("try { Confirm-SecureBootUEFI } catch { 'недоступно' }"),
            ps("try { manage-bde -status C: } catch { '' }"),
            ps("try { Get-Tpm | Format-List * } catch { '' }"),
            ps("Get-CimInstance Win32_OperatingSystem | Format-List *"))

    d = _blank(system or "неизвестна")
    d["ос"] = f"{system} — платформа не поддержана"
    return d


def render(d: dict) -> None:
    print("ПРОШИВКА И БАЗОВОЕ ПО")
    print(f"   платформа    {d['платформа']} · {d['ос']}")
    print(f"   ядро         {d['ядро']} · {d['архитектура']}")
    print(f"   машина       {d['производитель']} {d['модель']} · {d['серийный']}")
    if d["материнская_плата"] != NA:
        print(f"   плата        {d['материнская_плата']}")
    print(f"   прошивка     {d['прошивка_вендор']} {d['прошивка_версия']}"
          + (f" · {d['прошивка_дата']}" if d["прошивка_дата"] != NA else ""))
    print(f"   чип доверия  {d['чип_доверия']}")
    print(f"   Secure Boot  {d['secure_boot']}")
    print(f"   шифрование   {d['шифрование_диска']}")
    print(f"   защита ОС    {d['защита_системы']}")
    if not d["проверено_вживую"]:
        print("\n   🔴 Ветка этой платформы НЕ проверена на живой машине —")
        print("      разбор написан по документации и проверен на образцах.")
        print("      Расхождение здесь ожидаемо; сообщить о нём — ценнее,")
        print("      чем поверить выводу (`71` §7г-бис).")


# ========================================================== канарейка ========
# 🔴 ОБРАЗЦЫ ВЫВОДА. Единственный способ проверить разбор для платформы,
# которой нет под рукой. Приведены в том формате, в каком команды печатают
# на реальных системах; если формат окажется иным — тест это и покажет
# первым же запуском на живой машине, и образец правится по факту.
SAMPLE_LINUX_DMI = {
    "sys_vendor": "LENOVO", "product_name": "20XW00ABRT",
    "board_vendor": "LENOVO", "board_name": "20XW00ABRT",
    "bios_vendor": "LENOVO", "bios_version": "N32ET75W (1.50 )",
    "bios_date": "05/17/2023", "product_serial": "PF3ABCDE",
}
SAMPLE_LINUX_OSREL = 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.1 LTS"\nVERSION_ID="24.04"\n'
SAMPLE_WIN_BIOS = """
Manufacturer      : LENOVO
Name              : N32ET75W (1.50 )
ReleaseDate       : 20230517000000.000000+000
SMBIOSBIOSVersion : N32ET75W (1.50 )
SerialNumber      : PF3ABCDE
"""
SAMPLE_WIN_CS = "Manufacturer : LENOVO\nModel        : 20XW00ABRT\n"
SAMPLE_WIN_BOARD = "Manufacturer : LENOVO\nProduct      : 20XW00ABRT\n"
SAMPLE_WIN_OS = "Caption     : Microsoft Windows 11 Pro\nBuildNumber : 22631\n"
SAMPLE_MAC_HW = """
      Model Identifier: MacBookPro15,2
      System Firmware Version: 2103.100.6.0.0
      Serial Number (system): C02YX029JHC8
"""
SAMPLE_MAC_IBRIDGE = "      Model Name: Apple T2 Security Chip\n      Firmware Version: 23P5067\n"


def selftest() -> bool:
    """Разбор всех трёх платформ на образцах + инвариант формы ответа.

    🔴 Проверяется РАЗЛИЧЕНИЕ, а не то, что код исполняется: включённый
    Secure Boot и выключенный обязаны дать разные строки. Проверка,
    возвращающая одно и то же на любом входе, не проверяет ничего.
    """
    ok = True

    def check(cond: bool, why: str) -> None:
        nonlocal ok
        if not cond:
            print(f"🔴 {why}", file=sys.stderr)
            ok = False

    # --- форма ответа одинакова у всех веток ---
    for name, d in (("linux", parse_linux(SAMPLE_LINUX_DMI, SAMPLE_LINUX_OSREL,
                                          "SecureBoot enabled", "crypt",
                                          "SELinux status: enforcing", "2")),
                    ("windows", parse_windows(SAMPLE_WIN_BIOS, SAMPLE_WIN_CS,
                                              SAMPLE_WIN_BOARD, "True",
                                              "Protection On",
                                              "TpmPresent : True\nIsEnabled_InitialValue : True",
                                              SAMPLE_WIN_OS)),
                    ("macos", parse_macos(SAMPLE_MAC_HW, SAMPLE_MAC_IBRIDGE,
                                          "System Integrity Protection status: enabled.",
                                          "assessments enabled", "FileVault is On.",
                                          "x86_64"))):
        check(set(d) == set(KEYS), f"{name}: набор ключей разошёлся с KEYS")

    # --- Linux: поля извлечены, а не подставлены ---
    lin = parse_linux(SAMPLE_LINUX_DMI, SAMPLE_LINUX_OSREL, "SecureBoot enabled",
                      "crypt", "SELinux status: enforcing", "2")
    check(lin["прошивка_версия"] == "N32ET75W (1.50 )", "linux: версия BIOS не разобрана")
    check(lin["прошивка_дата"] == "05/17/2023", "linux: дата BIOS не разобрана")
    check(lin["ос"] == "Ubuntu 24.04.1 LTS", "linux: PRETTY_NAME не разобран")
    check(lin["secure_boot"] == "включён", "linux: Secure Boot не разобран")
    check(lin["серийный"] == "…BCDE", "linux: серийный не маскирован")
    check("enforcing" in lin["защита_системы"], "linux: SELinux не разобран")

    # 🔴 обратное направление: выключенный Secure Boot обязан отличаться
    lin_off = parse_linux(SAMPLE_LINUX_DMI, SAMPLE_LINUX_OSREL,
                          "SecureBoot disabled", "", "", "")
    check(lin_off["secure_boot"] == "выключен", "linux: выключенный SB не различён")
    check(lin_off["чип_доверия"] == NA, "linux: отсутствие TPM не признано")

    # --- Windows: дата приводится к ISO, `wmic`-формат не используется ---
    win = parse_windows(SAMPLE_WIN_BIOS, SAMPLE_WIN_CS, SAMPLE_WIN_BOARD,
                        "True", "Protection On",
                        "TpmPresent : True\nIsEnabled_InitialValue : True",
                        SAMPLE_WIN_OS)
    check(win["прошивка_дата"] == "2023-05-17", "windows: дата BIOS не приведена к ISO")
    check(win["ос"].startswith("Microsoft Windows 11 Pro"), "windows: ОС не разобрана")
    check("сборка 22631" in win["ос"], "windows: сборка не добавлена")
    check(win["secure_boot"] == "включён", "windows: Secure Boot не разобран")
    check("BitLocker" in win["шифрование_диска"], "windows: BitLocker не разобран")

    win_off = parse_windows(SAMPLE_WIN_BIOS, SAMPLE_WIN_CS, SAMPLE_WIN_BOARD,
                            "False", "Protection Off", "TpmPresent : False",
                            SAMPLE_WIN_OS)
    check(win_off["secure_boot"] == "выключен", "windows: выключенный SB не различён")
    check("выключена" in win_off["шифрование_диска"], "windows: выключенный BitLocker")

    # --- macOS: Intel и Apple Silicon различаются по существу ---
    mac = parse_macos(SAMPLE_MAC_HW, SAMPLE_MAC_IBRIDGE,
                      "System Integrity Protection status: enabled.",
                      "assessments enabled", "FileVault is On.", "x86_64")
    check("T2" in mac["чип_доверия"], "macos intel: чип T2 не разобран")
    check(mac["проверено_вживую"] is True, "macos intel: должна быть отметка о проверке")

    # 🔴 Apple Silicon: `SPiBridgeDataType` ПУСТ, и это не отказ, а устройство.
    arm = parse_macos(SAMPLE_MAC_HW, "", "System Integrity Protection status: enabled.",
                      "assessments enabled", "FileVault is On.", "arm64")
    check("Secure Enclave" in arm["чип_доверия"],
          "apple silicon: пустой iBridge принят за отказ, а не за отсутствие чипа")
    check(arm["проверено_вживую"] is False,
          "apple silicon: непроверенная ветка помечена как проверенная")
    check("iBoot" in arm["прошивка_вендор"], "apple silicon: вендор прошивки неверен")
    return ok


def main() -> int:
    if "--selftest" in sys.argv:
        ok = selftest()
        print("канарейка разбора прошивки: " + ("🟢 зелёная" if ok else "🔴 красная"))
        return 0 if ok else 1
    snap = collect()
    if "--json" in sys.argv:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        render(snap)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
