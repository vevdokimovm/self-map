#!/usr/bin/env python3
"""machine_probe.py — снимок состояния Mac: железо, нагрузка, диск, сеть, батарея.

ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «скилл, который будет считывать состояние сети,
нагрузки процессора, нагрузки мака, температуры — и всё это понятно, красиво
агрегировать; какое состояние железа, где проблема может быть».

ПОЧЕМУ СКРИПТ, А НЕ АГЕНТ. Числа снимаются командами, а не суждением модели.
Агент нужен там, где надо ИСТОЛКОВАТЬ снимок; сам снимок обязан быть
воспроизводимым и одинаковым от запуска к запуску (`/auto` §1.1: сначала факт
с диска, потом суждение).

🔴 ЧТО ЗДЕСЬ ЕСТЬ ЧЕСТНО, А ЧТО НЕТ:
  · температура CPU на Intel-маках доступна только через `powermetrics`,
    а он требует sudo. Без пароля отдаётся температура БАТАРЕИ (ioreg) —
    и она подписана именно так, а не выдаётся за температуру процессора;
  · здоровье SSD полноценно читает `smartctl` (brew smartmontools). Без него
    берётся `diskutil` — он говорит только Verified/Failing, без счётчиков износа;
  · скорость сети меряется `networkQuality` и занимает ~15 секунд, поэтому
    включается флагом `--net`, а не молча в каждом запуске.

ПРЕДУСЛОВИЯ:
  · macOS (проверяется по `uname`); на другой системе скрипт отказывается сразу;
  · штатные утилиты `sysctl`, `vm_stat`, `top`, `ioreg`, `diskutil` на месте.

ПОСТУСЛОВИЯ:
  · на stdout — читаемый срез, либо валидный JSON при `--json`;
  · каждый показатель, который снять не удалось, назван словом «недоступно»
    с причиной, а не пропущен и не заменён нулём.

ИНВАРИАНТ: скрипт только ЧИТАЕТ. Ни одной команды, меняющей состояние машины,
здесь нет и быть не должно — иначе замер начнёт влиять на измеряемое.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import re
from pathlib import Path
import shutil
import datetime as dt
import subprocess
import sys
import time
from datetime import datetime

# ── Пороги. Зелёное молчит; тревога — только на перейденном пороге.
#    Значения выбраны под эту машину (4 ядра, 8 ГБ) и объяснены строкой.
THRESHOLDS = {
    "load_per_core": 2.0,      # выше двух задач на ядро — очередь, а не работа
    "swap_used_mb": 1024,      # своп >1 ГБ означает, что памяти уже не хватает
    "disk_free_pct": 10,       # ниже 10 % macOS начинает вести себя странно
    "battery_health_pct": 80,  # Apple считает батарею изношенной ниже 80 %
    "mem_free_mb": 512,        # меньше — система живёт за счёт сжатия
    # 🔴 Дней без бэкапа. Порог 7 — не про аккуратность, а про то, что
    # накопитель распаян и замене не подлежит: восстановление возможно
    # ТОЛЬКО из копии. Отсутствие копий вовсе — отдельная тревога, не «8 дней».
    "дней без бэкапа": 7,
}


def sh(cmd: list[str], timeout: int = 10) -> str:
    """Выполнить и вернуть stdout. Отказ — пустая строка, НЕ исключение.

    Отсутствие утилиты — законное состояние (`71` §7ж: не пробовал ≠ не работает),
    поэтому вызывающий обязан различать пустоту и ноль.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def hardware() -> dict:
    out = sh(["system_profiler", "SPHardwareDataType"], timeout=30)
    def grab(label: str) -> str:
        m = re.search(rf"{label}:\s*(.+)", out)
        return m.group(1).strip() if m else "недоступно"
    mem_b = sh(["sysctl", "-n", "hw.memsize"]).strip()
    return {
        "модель": grab("Model Name"),
        "идентификатор": grab("Model Identifier"),
        "процессор": grab("Processor Name") or grab("Chip"),
        "ядер": grab("Total Number of Cores"),
        "память_гб": round(int(mem_b) / 1024**3) if mem_b.isdigit() else "недоступно",
        "macos": f"{platform.mac_ver()[0]} ({sh(['sw_vers', '-buildVersion']).strip()})",
        "архитектура": platform.machine(),
    }


def firmware(full_serial: bool = False, check_updates: bool = False) -> dict:
    """Прошивка и базовое ПО — то, что на PC зовётся BIOS/UEFI.

    🔴 ЗАКАЗ ВЛАДЕЛЬЦА 03.09.2026: *«пусть machine также считывает версию
    операционки, какой биос, какие все настройки самой базовой программы
    на компьютерах… и установщики операционных систем»*.

    **На Mac BIOS в привычном виде нет** — и это не придирка к слову, а разница
    в устройстве, меняющая ответ. У Intel-Mac роль прошивки играют:

      · `System Firmware Version` — EFI, ближайший аналог BIOS;
      · `OS Loader Version` — загрузчик;
      · чип **Apple T2** со своей прошивкой — на нём проверка загрузки,
        шифрование диска и Secure Boot. У этой машины он есть (MacBookPro15,2).

    В прошивку **нельзя зайти по F2** и там нечего настраивать: политики
    задаёт macOS, а меняются они из Recovery. Поэтому раздел показывает
    **состояние**, а не «настройки», которых нет.

    Настройки базового ПО, которые реально существуют и имеют значение:

      · **SIP** — защита системных файлов от изменения даже под root;
      · **Gatekeeper** — проверка подписи запускаемых программ;
      · **FileVault** — шифрование диска. 🔴 Для владельца без бэкапов это
        не отвлечённая строка: при отказе диска зашифрованные данные
        не вытащить из накопителя напрямую;
      · **XProtect / MRT** — антивирусные определения Apple, обновляются молча;
      · **автообновления** — включены ли скачивание и критические патчи.

    🔴 ЧЕГО НЕ ПОКАЗЫВАЕТ (`71` §7г-бис):
      · **политику Secure Boot** чипа T2 — читается только `bputil` из Recovery;
      · **доступные обновления** — `softwareupdate -l` ходит в сеть и занимает
        десятки секунд. Вынесено под `--updates`, чтобы обычный замер
        не превращался в сетевую операцию;
      · **серийный номер** маскируется: он опознаёт устройство, а замер
        попадает в отчёты. Полностью — только под `--full-serial`.
    """
    hw = sh(["system_profiler", "SPHardwareDataType"], timeout=30)
    ibr = sh(["system_profiler", "SPiBridgeDataType"], timeout=30)

    def grab(text: str, label: str) -> str:
        m = re.search(rf"{label}:\s*(.+)", text)
        return m.group(1).strip() if m else "недоступно"

    serial = grab(hw, r"Serial Number \(system\)")
    if not full_serial and serial != "недоступно" and len(serial) > 4:
        serial = "…" + serial[-4:]          # хвоста хватает, чтобы отличить машину

    sip = sh(["csrutil", "status"]).strip()
    gate = sh(["spctl", "--status"]).strip()
    vault = sh(["fdesetup", "status"]).strip()

    def xprotect() -> str:
        for b in ("/Library/Apple/System/Library/CoreServices/XProtect.bundle",
                  "/System/Library/CoreServices/XProtect.bundle"):
            v = sh(["defaults", "read", f"{b}/Contents/Info",
                    "CFBundleShortVersionString"]).strip()
            if v:
                return v
        return "недоступно"

    su = sh(["defaults", "read", "/Library/Preferences/com.apple.SoftwareUpdate"])
    def flag(key: str) -> str:
        m = re.search(rf"{key}\s*=\s*(\d)", su)
        return {"1": "вкл", "0": "выкл"}.get(m.group(1), "?") if m else "недоступно"

    # Установщики macOS: их держат ради переустановки без сети, весят 12+ ГБ,
    # и о них забывают — при диске на 7 % свободного это заметная величина.
    installers = []
    for d in (Path("/Applications"), Path.home() / "Applications"):
        if d.is_dir():
            for app in sorted(d.glob("Install macOS*.app")):
                size = sum(f.stat().st_size for f in app.rglob("*")
                           if f.is_file()) // 1024**2
                installers.append({"имя": app.name, "мб": size})

    return {
        "macos": f"{platform.mac_ver()[0]} ({sh(['sw_vers', '-buildVersion']).strip()})",
        "ядро": platform.release(),
        "прошивка_efi": grab(hw, "System Firmware Version"),
        "загрузчик": grab(hw, "OS Loader Version"),
        "чип_безопасности": grab(ibr, "Model Name"),
        "прошивка_чипа": grab(ibr, "Firmware Version"),
        "блокировка_активации": grab(hw, "Activation Lock Status"),
        "серийный": serial,
        "sip": "включён" if "enabled" in sip else ("выключен" if sip else "недоступно"),
        "gatekeeper": "включён" if "assessments enabled" in gate else
                      ("выключен" if gate else "недоступно"),
        "filevault": "включён" if "FileVault is On" in vault else
                     ("выключен" if vault else "недоступно"),
        "xprotect": xprotect(),
        "автообновление_скачивание": flag("AutomaticDownload"),
        "автообновление_критические": flag("CriticalUpdateInstall"),
        "установщики_macos": installers,
        # 🔴 Только по флагу: `softwareupdate -l` ходит в сеть. Обычный замер
        # обязан оставаться локальным — иначе он перестаёт работать без сети
        # и начинает зависеть от чужого сервера (`71` §7ж).
        "обновления": _updates() if check_updates else "не спрашивались (--updates)",
    }


def _updates() -> str:
    """Доступные обновления macOS. Отдельно — потому что это сетевой вызов."""
    out = sh(["softwareupdate", "-l"], timeout=180)
    if not out.strip():
        return "недоступно (нет ответа)"
    if "No new software available" in out:
        return "нет доступных"
    found = [l.strip("* ").strip() for l in out.splitlines()
             if l.strip().startswith("*") or "Label:" in l]
    return "; ".join(found[:5]) if found else "ответ не разобран"


def load() -> dict:
    top = sh(["top", "-l1", "-n0"], timeout=20)
    m = re.search(r"Load Avg:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)", top)
    # 🔴 hw.ncpu считает ПОТОКИ (8 у i5 с hyper-threading), а не ядра (4).
    # Делить load на 8 значит вдвое занизить нагрузку — и объявить
    # «простаивает» машину, у которой очередь. Нужен hw.physicalcpu.
    cores = int(sh(["sysctl", "-n", "hw.physicalcpu"]).strip() or 0) or \
            int(sh(["sysctl", "-n", "hw.ncpu"]).strip() or 1)
    la1 = float(m.group(1)) if m else None
    cpu = re.search(r"CPU usage:\s*([\d.]+)% user,\s*([\d.]+)% sys,\s*([\d.]+)% idle", top)
    return {
        "ядер": cores,
        "load_1_5_15": [float(m.group(i)) for i in (1, 2, 3)] if m else "недоступно",
        "load_на_ядро": round(la1 / cores, 2) if la1 is not None else "недоступно",
        "cpu_user_sys_idle": [float(cpu.group(i)) for i in (1, 2, 3)] if cpu else "недоступно",
    }


def memory() -> dict:
    vm = sh(["vm_stat"])
    page = 4096
    pm = re.search(r"page size of (\d+) bytes", vm)
    if pm:
        page = int(pm.group(1))
    def pages(label: str) -> int:
        m = re.search(rf"{label}:\s+(\d+)", vm)
        return int(m.group(1)) if m else 0
    free_mb = (pages("Pages free") + pages("Pages speculative")) * page // 1024**2
    swap = sh(["sysctl", "-n", "vm.swapusage"])
    sm = re.search(r"used\s*=\s*([\d.]+)M", swap)
    return {
        "свободно_мб": free_mb,
        "сжато_мб": pages("Pages occupied by compressor") * page // 1024**2,
        "своп_использован_мб": round(float(sm.group(1))) if sm else "недоступно",
    }


def disks() -> dict:
    df = sh(["df", "-k", "/System/Volumes/Data"]).splitlines()
    used = free = pct = "недоступно"
    if len(df) > 1:
        f = df[1].split()
        used, free = round(int(f[2]) / 1024**2, 1), round(int(f[3]) / 1024**2, 1)
        pct = round(free / (used + free) * 100, 1)
    info = sh(["diskutil", "info", "disk0"])
    def grab(label: str) -> str:
        m = re.search(rf"{label}:\s*(.+)", info)
        return m.group(1).strip() if m else "недоступно"
    smart = {"состояние": grab("SMART Status")}
    if shutil.which("smartctl"):
        s = sh(["smartctl", "-A", "/dev/disk0"], timeout=20)
        for key, label in (("Percentage Used", "износ_проц"),
                           ("Data Units Written", "записано")):
            m = re.search(rf"{key}:?\s*([\d,.]+)", s)
            if m:
                smart[label] = m.group(1)
    else:
        smart["подробности"] = "недоступно: нет smartctl (brew install smartmontools)"
    return {"модель": grab("Device / Media Name"), "занято_гб": used,
            "свободно_гб": free, "свободно_проц": pct, "smart": smart}


def battery() -> dict:
    io = sh(["ioreg", "-r", "-c", "AppleSmartBattery"])
    def num(key: str):
        m = re.search(rf'"{key}"\s*=\s*(\d+)', io)
        return int(m.group(1)) if m else None
    design, now, cycles = num("DesignCapacity"), num("AppleRawMaxCapacity"), num("CycleCount")
    temp = num("Temperature")
    return {
        "циклов": cycles if cycles is not None else "недоступно",
        "здоровье_проц": round(now / design * 100, 1) if design and now else "недоступно",
        "температура_батареи_c": round(temp / 100, 1) if temp else "недоступно",
        "питание": "сеть" if "AC Power" in sh(["pmset", "-g", "batt"]) else "батарея",
        # 🔴 Честно: это температура БАТАРЕИ. Температура CPU на Intel требует
        # sudo powermetrics и потому здесь не выдаётся за неё.
        "температура_cpu": "недоступно без sudo (powermetrics)",
    }


def network(measure: bool = False) -> dict:
    """Состояние сети.

    🔴 Маршрут по умолчанию при включённом VPN указывает на туннель (`utunNN`),
    у которого нет адреса в понимании `ipconfig getifaddr` — первая редакция
    из-за этого печатала «нет адреса» и «нет ответа» на исправной сети.
    Поэтому туннель называется отдельно, а адрес берётся с ФИЗИЧЕСКОГО
    интерфейса, найденного перебором.
    """
    svc = sh(["route", "-n", "get", "default"])
    m = re.search(r"interface:\s*(\S+)", svc)
    route_iface = m.group(1) if m else "недоступно"
    vpn = route_iface.startswith(("utun", "ipsec", "ppp"))
    iface, ip = route_iface, ""
    if not vpn:
        ip = sh(["ipconfig", "getifaddr", route_iface]).strip()
    if not ip:
        # физический интерфейс: первый из en*, у которого есть адрес
        for cand in re.findall(r"^(en\d+):", sh(["ifconfig"]), re.M):
            got = sh(["ipconfig", "getifaddr", cand]).strip()
            if got:
                iface, ip = cand, got
                break
    ping = sh(["ping", "-c", "3", "-t", "5", "1.1.1.1"], timeout=15)
    pm = re.search(r"=\s*[\d.]+/([\d.]+)/", ping)
    res = {
        "интерфейс": iface,
        "ip": ip or "нет адреса",
        "пинг_мс": round(float(pm.group(1)), 1) if pm else "нет ответа",
        "через_vpn": "да" if vpn else "нет",
        "маршрут_по_умолчанию": route_iface,
    }
    if measure and shutil.which("networkQuality"):
        q = sh(["networkQuality", "-s"], timeout=90)
        for key, label in (("Downlink capacity", "скачивание"), ("Uplink capacity", "отдача")):
            m = re.search(rf"{key}:\s*([\d.]+\s*\w+ps)", q)
            res[label] = m.group(1) if m else "недоступно"
    elif measure:
        res["скорость"] = "недоступно: нет networkQuality"
    return res


def top_processes(n: int = 5) -> list[dict]:
    out = sh(["ps", "-Aceo", "pid,pcpu,pmem,rss,comm", "-r"], timeout=20)
    rows = []
    for line in out.splitlines()[1:n + 1]:
        f = line.split(None, 4)
        if len(f) == 5:
            rows.append({"pid": f[0], "cpu": float(f[1]), "mem": float(f[2]),
                         "rss_мб": round(int(f[3]) / 1024), "имя": f[4]})
    return rows


def fans_and_temps() -> dict:
    """Вентиляторы и температуры — как показывает Macs Fan Control.

    ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «добавь ещё инфу по вентиляторам,
    как у меня в приложении Fans».

    🔴 ПОЧЕМУ ЭТО СЛОЖНЕЕ, ЧЕМ КАЖЕТСЯ. Обороты вентиляторов и температуры
    процессора живут в контроллере SMC — отдельном чипе. Читать его умеют:

      · `powermetrics --samplers smc` — штатный, но требует **sudo**;
      · сторонние утилиты (smcFanControl, iStats, Macs Fan Control) —
        ставят свой помощник с повышенными правами;
      · `ioreg` — на Intel-маках датчиков SMC **не показывает вовсе**
        (проверено 02.09.2026: ноль совпадений по `AppleSMC`).

    В brew на сентябрь 2026 подходящей формулы нет — проверено поиском
    по `fan` и `smc`, оба дали мусор.

    Поэтому: с sudo — реальные обороты и температуры; без sudo — честное
    «недоступно» и температура батареи как единственное, что отдаётся
    без прав. Выдавать второе за первое нельзя: батарея и процессор
    греются по-разному.
    """
    res = {"источник": "недоступно"}

    # ── путь 1: powermetrics, если пароль уже введён в этой сессии
    out = sh(["sudo", "-n", "powermetrics", "--samplers", "smc",
              "-n1", "-i", "200"], 25)
    if out.strip():
        fans, temps = [], {}
        for line in out.splitlines():
            low = line.lower()
            if "fan" in low and ":" in line:
                fans.append(line.strip())
            elif "die temperature" in low or "temperature" in low:
                k, _, v = line.partition(":")
                temps[k.strip()] = v.strip()
        if fans or temps:
            res = {"источник": "powermetrics (sudo)",
                   "вентиляторы": fans or "не найдены в выводе",
                   "температуры": temps or "не найдены"}
            return res

    # ── путь 2: батарея — единственное без прав, и это подписано честно
    io = sh(["ioreg", "-r", "-c", "AppleSmartBattery"])
    m = re.search(r'"Temperature"\s*=\s*(\d+)', io)
    res["температура_батареи_c"] = round(int(m.group(1)) / 100, 1) if m else "недоступно"
    res["🔴 оговорка"] = (
        "обороты вентиляторов и температура CPU требуют sudo: "
        "`sudo powermetrics --samplers smc -n1`. Показанное здесь — "
        "температура БАТАРЕИ, она греется иначе, чем процессор, "
        "и заменой не является")
    res["как_получить"] = "sudo python3 machine_probe.py — тогда раздел заполнится"
    return res


def top_by_resource(n: int = 6) -> dict:
    """Процессы по энергии, диску и сети — как в Activity Monitor, а с sudo лучше.

    🔴 САМОИСПРАВЛЕНИЕ 02.09.2026. Прежняя версия объявляла две вещи
    невозможными: «энергия в ваттах недоступна» и «диск по процессам
    невозможен, iotop в macOS не существует».

    **Первое верно только без sudo, второе неверно вовсе.** `man powermetrics`
    прямо описывает `--show-process-io` и `--show-process-netstats`:
    *«will give you this information on a per process basis»*. То есть
    отсутствие `iotop` не означает отсутствия механизма — оно означает
    отсутствие ОДНОЙ утилиты, а нужный механизм лежит в другой.

    Урок тот же, что с Tool Search: «инструмента X нет» ≠ «задача нерешаема».
    Проверять надо возможность, а не наличие привычного имени.

    С sudo: реальные ватты, реальные байты чтения и записи по процессам.
    Без sudo: приближение по времени CPU и `nettop`, и это подписано.
    """
    res = {}

    # ── полный путь: powermetrics с тремя сэмплерами за один прогон
    full = sh(["sudo", "-n", "powermetrics",
               "--samplers", "tasks,cpu_power,disk,network",
               "--show-process-energy", "--show-process-io",
               "--show-process-netstats",
               "-n1", "-i", "500"], 40)

    if full.strip():
        res["источник"] = "powermetrics (sudo) — точные значения"
        rows = []
        for line in full.splitlines():
            f = line.split()
            # строка процесса: имя, pid, потом числа. Заголовки пропускаем.
            if len(f) >= 6 and f[1].isdigit() and not line.startswith(" " * 4):
                try:
                    rows.append({"имя": f[0][:30], "pid": f[1],
                                 "энергия": float(f[3]) if _num(f[3]) else 0.0,
                                 "строка": line.strip()})
                except (ValueError, IndexError):
                    continue
        if rows:
            rows.sort(key=lambda r: -r["энергия"])
            res["по_энергии"] = [{"имя": r["имя"], "pid": r["pid"],
                                  "энергия": r["энергия"]} for r in rows[:n]]

        # суммарная мощность пакета — то, что Activity Monitor не показывает вовсе
        m = re.search(r"Intel energy model derived package power \(CPUs\+GT\+SA\): ([\d.]+)W", full)
        if m:
            res["мощность_пакета_вт"] = float(m.group(1))
        m = re.search(r"CPU Average frequency as fraction of nominal: ([\d.]+)%", full)
        if m:
            res["частота_от_номинала_проц"] = float(m.group(1))

        # ── диск и сеть по процессам: разделы вывода
        for key, header in (("диск_по_процессам", "DISK"),
                            ("сеть_по_процессам", "NETWORK")):
            block = _section(full, header)
            if block:
                res[key] = block[:n]
        return res

    # ── путь без прав: приближение, и оно так и называется
    res["источник"] = "без sudo — приближение"
    out = sh(["ps", "-Aceo", "pid,time,%cpu,comm", "-r"], 20)
    res["по_времени_cpu"] = []
    for line in out.splitlines()[1:n + 1]:
        f = line.split(None, 3)
        if len(f) == 4:
            res["по_времени_cpu"].append(
                {"pid": f[0], "время_cpu": f[1], "cpu": float(f[2]), "имя": f[3]})
    res["🔴 оговорка"] = (
        "время CPU — прокси, не ватты; диск и сеть по процессам без sudo "
        "недоступны. Точные значения: sudo python3 machine_probe.py")
    return res


def _num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _section(text: str, header: str) -> list[str]:
    """Вырезать блок вывода powermetrics по заголовку."""
    lines = text.splitlines()
    out, inside = [], False
    for line in lines:
        if line.strip().startswith("***") and header in line:
            inside = True
            continue
        if inside:
            if line.strip().startswith("***"):
                break
            if line.strip():
                out.append(line.strip())
    return out


# ── Известные пожиратели, найденные разбором 02.09.2026 ──────────────────
#
# 🔴 Список не выдуман, а получен ценой полугода перегрева. Каждая запись —
# процесс, который грузит машину, НЕ БУДУЧИ ВИДИМЫМ владельцу: у него нет
# окна, нет иконки в доке, и в Activity Monitor он теряется среди сотни строк.
#
# Формат: имя → (что это, что делать)
KNOWN_HOGS = {
    "StorageManagementService": (
        "пересчитывает экран «Хранилище» в Системных настройках",
        "🔴 ЗАКРЫТЬ окно Системных настроек. Пока оно открыто, служба "
        "обходит весь диск и запускает 21 расширение-счётчик"),
    "ApplicationsStorageExtension": (
        "считает размер приложений для того же экрана",
        "закрыть Системные настройки — исчезнет вместе со службой"),
    "mds_stores": (
        "индексатор Spotlight",
        "исключить ~/repos: Настройки → Spotlight → Search Privacy"),
    "photoanalysisd": (
        "распознаёт лица и объекты в Фото",
        "работает волнами после импорта; сам закончит"),
    "cloudphotod": (
        "синхронизация Фото с iCloud",
        "проверить квоту iCloud: brctl quota"),
    "bird": (
        "демон iCloud Drive",
        "при полной квоте работает вхолостую — освободить место в iCloud"),
    "fileproviderd": (
        "выселение файлов в облако",
        "снять «Оптимизацию хранилища» в настройках iCloud Drive"),
    "backupd": (
        "Time Machine",
        "нормально во время копирования; если постоянно — проверить диск"),
    "kernel_task": (
        "ядро; высокая доля часто означает борьбу с ПЕРЕГРЕВОМ",
        "🔴 не причина, а симптом: ядро искусственно тормозит систему, "
        "чтобы сбить температуру. Искать, что греет"),
}


def _secs(s: str) -> int:
    """`ps` печатает время как MM:SS.ss или HH:MM:SS."""
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    except ValueError:
        pass
    return 0


def _etime_secs(s: str) -> int:
    """`etime`: [[DD-]HH:]MM:SS."""
    days = 0
    if "-" in s:
        d, s = s.split("-", 1)
        days = int(d)
    parts = [int(x) for x in s.split(":")] if s.replace(":", "").isdigit() else []
    if len(parts) == 3:
        base = parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:
        base = parts[0] * 60 + parts[1]
    else:
        return 0
    return days * 86400 + base


# 🔴 ЗАКАЗ ВЛАДЕЛЬЦА 03.09.2026: «machine умеет впн также считывать да?
# трафик впн интеа? если нет сделай».
#
# ПОВОД. В ночь на 03.09 вентиляторы вышли на максимум при load 10.35 —
# заметно выше эталона 8.22, снятого двумя часами ранее на той же связке
# «Dota + агент». Виновником оказался `Tunnel.appex` (VPN Happ): **26 % одного
# ядра постоянно, пики до 156 %**. Прежний срез его не показывал вовсе:
# `network()` отвечал только «через_vpn: да» — факт, из которого не следует
# ни цена, ни объём.
#
# 🔴 ПОЧЕМУ «ДА/НЕТ» НЕДОСТАТОЧНО. VPN — не переключатель, а работа: он
# шифрует каждый пакет, и его нагрузка пропорциональна трафику. При игре
# (непрерывный поток) он стоит столько же, сколько сама игра. Владелец живёт
# в России и без VPN работать не может — значит вопрос не «выключить или нет»,
# а «сколько он берёт и не сломался ли». Ответить на это можно только числами.
#
# ГРАНИЦА ЧЕСТНОСТИ: трафик считается по СЧЁТЧИКАМ ИНТЕРФЕЙСА с момента
# загрузки системы. Это не «сколько прошло через VPN за сессию» и не разбивка
# по приложениям — такого механизма в macOS нет без прав администратора.

VPN_HINTS = ("tunnel", "openvpn", "wireguard", "wg-", "amneziawg",
             "xray", "sing-box", "v2ray", "outline", "tailscaled",
             "nordvpn", "protonvpn", "mullvad")


def _bytes_human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def _iface_traffic() -> dict:
    """Принято/отдано по интерфейсам — из счётчиков `netstat -ib`.

    Строк на интерфейс несколько (Link, IPv6, IPv4) с ОДНИМИ И ТЕМИ ЖЕ
    счётчиками. Берётся первая (`<Link#N>`) — суммировать их значило бы
    утроить трафик.
    """
    out = sh(["netstat", "-ib"], timeout=15)
    seen: dict[str, dict] = {}
    for line in out.splitlines()[1:]:
        f = line.split()
        if len(f) < 10 or not f[2].startswith("<Link"):
            continue
        name = f[0]
        if name in seen:
            continue
        try:
            seen[name] = {"принято": int(f[6]), "отдано": int(f[9])}
        except (ValueError, IndexError):
            continue
    return seen


def vpn_state(uptime_s: int = 0) -> dict:
    r"""VPN: кто держит туннель, сколько ест, сколько прогнал."""
    route = sh(["route", "-n", "get", "default"])
    m = re.search(r"interface:\s*(\S+)", route)
    iface = m.group(1) if m else ""
    tunnels = re.findall(r"^(utun\d+|ipsec\d+|ppp\d+):", sh(["ifconfig"]), re.M)
    active = bool(iface) and iface.startswith(("utun", "ipsec", "ppp"))

    res: dict = {
        "активен": "да" if active else "нет",
        "маршрут_через": iface or "недоступно",
        "туннелей_поднято": len(tunnels),
    }

    # ── кто его держит и чего это стоит
    procs = []
    for line in sh(["ps", "-Aceo", "pid,etime,time,%cpu,comm"], 20).splitlines()[1:]:
        f = line.split(None, 4)
        if len(f) != 5:
            continue
        name = f[4].strip()
        if not any(h in name.lower() for h in VPN_HINTS):
            continue
        cpu_s = _secs(f[2])
        run_s = _etime_secs(f[1])
        procs.append({
            "процесс": name, "pid": f[0],
            "работает": f[1], "время_cpu": f[2], "сейчас_проц": float(f[3]),
            # 🔴 Доля считается от ВРЕМЕНИ РАБОТЫ процесса, а не от аптайма
            # системы: VPN включают и выключают, и делить на аптайм значило бы
            # занизить его цену во столько раз, во сколько он моложе системы.
            "доля_ядра_проц": round(cpu_s / run_s * 100, 1) if run_s else None,
        })
    procs.sort(key=lambda p: -(p["доля_ядра_проц"] or 0))
    res["процессы"] = procs

    # ── трафик
    traffic = _iface_traffic()
    tun_in = sum(traffic.get(t, {}).get("принято", 0) for t in tunnels)
    tun_out = sum(traffic.get(t, {}).get("отдано", 0) for t in tunnels)
    phys = {k: v for k, v in traffic.items() if k.startswith("en")}
    res["трафик"] = {
        "туннели_принято": _bytes_human(tun_in),
        "туннели_отдано": _bytes_human(tun_out),
        "физические": {k: {"принято": _bytes_human(v["принято"]),
                           "отдано": _bytes_human(v["отдано"])}
                       for k, v in phys.items()},
        "🔴 оговорка": ("счётчики интерфейсов с момента загрузки системы, "
                        "не за сессию; разбивки по приложениям в macOS нет "
                        "без прав администратора"),
    }
    # 🔴 Ноль на туннеле при активном VPN — не ошибка замера. Многие клиенты
    # (Happ, Outline, sing-box) работают через NetworkExtension: пакеты идут
    # мимо BSD-счётчиков utun, и netstat честно показывает ноль. Тогда
    # единственная измеримая цена VPN — процессорное время его процесса.
    if active and not (tun_in or tun_out):
        res["трафик"]["🔴 ноль на туннеле"] = (
            "клиент работает через NetworkExtension — пакеты минуют счётчики "
            "utun. Не ошибка: цену VPN здесь показывает только время CPU")
    return res


def hidden_load() -> dict:
    """Фоновые процессы, съевшие заметную долю CPU за всё время работы.

    🔴 МЕРИТСЯ НАКОПЛЕННОЕ ВРЕМЯ, А НЕ МГНОВЕННЫЙ ПРОЦЕНТ, и это главное
    решение здесь. Фоновая служба работает волнами: между проходами она спит,
    и одиночный замер `%CPU` показывает честный ноль.

    Именно на этом я ошибся 02.09.2026: увидел 0.0 %, объявил проблему
    решённой, а через минуту тот же процесс дал 32 %. Долю от аптайма
    обмануть нельзя — съеденное время не исчезает между замерами.
    """
    up = 0
    m = re.search(r"sec\s*=\s*(\d+)", sh(["sysctl", "-n", "kern.boottime"]))
    if m:
        up = int(time.time()) - int(m.group(1))
    if not up:
        return {"ошибка": "не удалось узнать аптайм"}

    def secs(s: str) -> int:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(float(parts[1]))
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        except ValueError:
            pass
        return 0

    rows = []
    for line in sh(["ps", "-Aceo", "pid,time,%cpu,comm"], 25).splitlines()[1:]:
        f = line.split(None, 3)
        if len(f) != 4:
            continue
        s = secs(f[1])
        share = s / up * 100 if s else 0
        if share < 5.0:
            continue
        name = f[3].strip()
        known = KNOWN_HOGS.get(name)
        rows.append({"имя": name, "доля_проц": round(share, 1),
                     "время": f[1], "сейчас": float(f[2]),
                     "что_это": known[0] if known else "",
                     "что_делать": known[1] if known else ""})
    rows.sort(key=lambda r: -r["доля_проц"])
    return {"аптайм_ч": round(up / 3600, 1), "процессы": rows}


def open_apps() -> list[dict]:
    """Открытые приложения с окнами и их вес — что видно владельцу.

    В отличие от `hidden_load`, эти процессы видны: у них есть окна.
    Показываются вместе, чтобы было ясно, где нагрузка от работы,
    а где от невидимого фона.
    """
    out = sh(["ps", "-Axo", "pid,%cpu,rss,comm"], 25)
    apps = []
    for line in out.splitlines()[1:]:
        f = line.split(None, 3)
        if len(f) != 4 or "/Applications/" not in f[3]:
            continue
        if ".app/Contents/MacOS/" not in f[3]:
            continue
        name = f[3].split(".app/")[0].split("/")[-1]
        try:
            apps.append({"имя": name, "cpu": float(f[1]),
                         "память_мб": int(f[2]) // 1024})
        except ValueError:
            continue
    # склеиваем процессы одного приложения (у Chrome их десятки)
    merged: dict = {}
    for a in apps:
        m = merged.setdefault(a["имя"], {"имя": a["имя"], "cpu": 0.0,
                                         "память_мб": 0, "процессов": 0})
        m["cpu"] += a["cpu"]
        m["память_мб"] += a["память_мб"]
        m["процессов"] += 1
    return sorted(merged.values(), key=lambda a: -a["память_мб"])[:8]


def diagnose(snap: dict) -> list[str]:
    """Перейденные пороги — и только они. Зелёное молчит намеренно."""
    bad = []
    lp = snap["нагрузка"].get("load_на_ядро")
    if isinstance(lp, (int, float)) and lp >= THRESHOLDS["load_per_core"]:
        bad.append(f"нагрузка {lp} на ядро (порог {THRESHOLDS['load_per_core']}) — "
                   f"очередь задач длиннее, чем машина успевает разбирать")
    sw = snap["память"].get("своп_использован_мб")
    if isinstance(sw, (int, float)) and sw >= THRESHOLDS["swap_used_mb"]:
        bad.append(f"своп {sw} МБ (порог {THRESHOLDS['swap_used_mb']}) — "
                   f"оперативной памяти не хватает, машина пишет её на диск")
    mf = snap["память"].get("свободно_мб")
    if isinstance(mf, (int, float)) and mf <= THRESHOLDS["mem_free_mb"]:
        bad.append(f"свободной памяти {mf} МБ (порог {THRESHOLDS['mem_free_mb']})")
    dp = snap["диск"].get("свободно_проц")
    if isinstance(dp, (int, float)) and dp <= THRESHOLDS["disk_free_pct"]:
        bad.append(f"на диске свободно {dp} % (порог {THRESHOLDS['disk_free_pct']} %)")
    bh = snap["батарея"].get("здоровье_проц")
    if isinstance(bh, (int, float)) and bh <= THRESHOLDS["battery_health_pct"]:
        bad.append(f"здоровье батареи {bh} % (порог {THRESHOLDS['battery_health_pct']} %) — "
                   f"{snap['батарея'].get('циклов')} циклов")
    # 🔴 «Данных нет» ≠ «диск сломан». Найдено канарейкой 03.09.2026: при
    # отсутствующем ключе `.get()` возвращает None, None не входил в список
    # исправных состояний — и снимок без данных SMART выдавал тревогу
    # «SMART диска: None». Ложная тревога обучает не читать вывод, а это
    # дороже позднего замечания (тот же довод, что у порога «минут тишины»).
    smart = snap["диск"]["smart"].get("состояние")
    if smart not in ("Verified", "недоступно", None, ""):
        bad.append(f"SMART диска: {smart}")

    # 🔴 Защита системы. Порог — «выключено», а не число: у этих настроек
    # два состояния, и одно из них дефект. Молчать о выключенном FileVault
    # при отсутствии бэкапов особенно нельзя: при отказе диска данные
    # не вытащить напрямую из накопителя — а он тут распаян.
    f = snap.get("прошивка", {})
    for ключ, имя in (("filevault", "FileVault — шифрование диска"),
                      ("sip", "SIP — защита системных файлов"),
                      ("gatekeeper", "Gatekeeper — проверка подписи программ")):
        if f.get(ключ) == "выключен":
            bad.append(f"🔴 {имя} ВЫКЛЮЧЕН")
    if f.get("автообновление_критические") == "выкл":
        bad.append("критические обновления безопасности не ставятся автоматически")

    b = snap.get("бэкап", {})
    if b.get("последняя_копия", "").startswith("🔴"):
        bad.append("🔴 РЕЗЕРВНЫХ КОПИЙ НЕТ ВООБЩЕ — накопитель распаян, "
                   "восстанавливать будет неоткуда")
    elif isinstance(b.get("дней_без_бэкапа"), int) and \
            b["дней_без_бэкапа"] >= THRESHOLDS["дней без бэкапа"]:
        bad.append(f"последний бэкап {b['дней_без_бэкапа']} дней назад "
                   f"(порог {THRESHOLDS['дней без бэкапа']})")
    return bad


# ── Оценка износа компонентов ───────────────────────────────────────────
#
# ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «оценка состояния ноута, его компонентов…
# сколько проживёт, насколько ему плохо, нужна ли починка и насколько важно».
#
# 🔴 ЧЕСТНАЯ ГРАНИЦА, БЕЗ КОТОРОЙ ОЦЕНКА ВРЁТ. Отказ электроники —
# не износ, а событие: он приходит внезапно и предсказанию по счётчикам
# не поддаётся. Здесь оценивается ТОЛЬКО то, у чего есть измеримый ресурс:
# циклы батареи, статус SMART, свободное место. Всё остальное — материнская
# плата, клавиатура, экран, разъёмы — не оценивается вовсе, и об этом
# сказано прямо, а не заменено успокоительным «всё хорошо».
#
# 🔴 «Сколько проживёт» считается только для БАТАРЕИ и только по ЛИНЕЙНОЙ
# экстраполяции циклов. Это грубо: деградация нелинейна и зависит от
# температуры и глубины разрядов. Число даётся как порядок величины,
# и рядом стоит оговорка.

# Ресурс батареи по спецификации Apple для ноутбуков с 2010 года.
BATTERY_RATED_CYCLES = 1000


def backup_state() -> dict:
    """Есть ли резервные копии и когда была последняя.

    🔴 Заведено 02.09.2026, и повод стоил разбора. Time Machine показывал
    настроенное назначение и включённый автобэкап — а копий не существовало
    НИ ОДНОЙ: диск назначения отключён, и система об этом молчит.

    Отсюда правило проверки: спрашивать не «настроен ли», а «когда была
    последняя копия». Настройка без копии неотличима от копии по всем
    признакам, кроме одного — самой копии.
    """
    dest = sh(["tmutil", "destinationinfo"], 20)
    name = re.search(r"Name\s*:\s*(.+)", dest)
    latest = sh(["tmutil", "latestbackup"], 30).strip()
    listing = sh(["tmutil", "listbackups"], 30)

    res = {
        "назначение": name.group(1).strip() if name else "не настроено",
        "последняя_копия": latest or "🔴 НЕТ НИ ОДНОЙ",
        "дней_без_бэкапа": None,
    }
    if latest:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", latest)
        if m:
            when = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            res["дней_без_бэкапа"] = (dt.date.today() - when).days
    elif "No machine directory" in listing or not listing.strip():
        res["🔴 диагноз"] = ("назначение настроено, копий не существует — "
                            "диск назначения, вероятно, отключён")
    return res


def health() -> dict:
    """Износ компонентов и остаток ресурса — там, где он измерим.

    Отвечает не «сломается ли», а «сколько ресурса израсходовано».
    Разница существенна: первое непредсказуемо, второе считается.
    """
    io = sh(["ioreg", "-r", "-c", "AppleSmartBattery"])

    def num(key: str):
        m = re.search(rf'"{key}"\s*=\s*(\d+)', io)
        return int(m.group(1)) if m else None

    design, now = num("DesignCapacity"), num("AppleRawMaxCapacity")
    cycles, fail = num("CycleCount"), num("PermanentFailureStatus")
    cond = re.search(r"Condition:\s*(.+)", sh(["system_profiler", "SPPowerDataType"], 30))

    items = []

    # ── Батарея: единственный компонент с объявленным ресурсом
    if cycles is not None and design and now:
        wear = round(100 - now / design * 100, 1)
        left_cycles = max(BATTERY_RATED_CYCLES - cycles, 0)
        # Расход циклов в день неизвестен (нет истории), поэтому берётся
        # средний бытовой ориентир 0.7 цикла в день и НАЗЫВАЕТСЯ допущением.
        months = round(left_cycles / 0.7 / 30) if left_cycles else 0
        verdict = ("менять пора" if wear >= 30 or (cond and "Service" in cond.group(1))
                   else "изношена, но работает" if wear >= 20 else "в норме")
        items.append({
            "узел": "батарея",
            "износ_проц": wear,
            "израсходовано_ресурса_проц": round(cycles / BATTERY_RATED_CYCLES * 100),
            "состояние_по_macos": cond.group(1).strip() if cond else "недоступно",
            "вердикт": verdict,
            "остаток_циклов": left_cycles,
            "оценка_месяцев": months,
            "🔴 оговорка": "линейная экстраполяция при допущении 0.7 цикла в день; "
                           "деградация нелинейна, число — порядок величины",
            "аварийный_отказ": "нет" if fail == 0 else f"🔴 код {fail}",
        })

    # ── Диск: SMART без smartctl говорит только «жив / умирает»
    smart = re.search(r"SMART Status:\s*(.+)", sh(["diskutil", "info", "disk0"]))
    st = smart.group(1).strip() if smart else "недоступно"
    disk = {
        "узел": "накопитель",
        "smart": st,
        "вердикт": "в норме" if st == "Verified" else f"🔴 {st}",
    }
    if shutil.which("smartctl"):
        s = sh(["smartctl", "-a", "/dev/disk0"], timeout=30)

        def field(pat: str, cast=int):
            m = re.search(pat, s)
            return cast(m.group(1).replace(",", "")) if m else None

        used = field(r"Percentage Used:\s*(\d+)%")
        spare = field(r"Available Spare:\s*(\d+)%")
        spare_min = field(r"Available Spare Threshold:\s*(\d+)%")
        written = field(r"Data Units Written:\s*([\d,]+)")
        hours = field(r"Power On Hours:\s*([\d,]+)")
        cycles = field(r"Power Cycles:\s*([\d,]+)")
        unsafe = field(r"Unsafe Shutdowns:\s*([\d,]+)")
        warn = re.search(r"Critical Warning:\s*(0x[0-9a-f]+)", s)

        disk.update({
            "израсходовано_ресурса_проц": used,
            "резерв_блоков_проц": spare,
            "резерв_порог_проц": spare_min,
            "записано_тб": round(written * 512 * 1000 / 1e12, 1) if written else None,
            "часов_работы": hours,
            "включений": cycles,
            "некорректных_выключений": unsafe,
            "критическое_предупреждение": warn.group(1) if warn else "недоступно",
        })

        # 🔴 ВЕРДИКТ СТРОИТСЯ НА ДВУХ ЧИСЛАХ, А НЕ НА ОДНОМ, и это важно.
        #
        # `Percentage Used` — счётчик ИЗРАСХОДОВАННОГО РЕСУРСА ЗАПИСИ по мерке
        # производителя. Он может превысить 100 %, и это не поломка: гарантийный
        # ресурс кончился, ячейки работают дальше.
        #
        # `Available Spare` — доля НЕТРОНУТЫХ резервных блоков, которыми диск
        # подменяет отказавшие. Вот она и есть настоящий признак умирания:
        # пока резерв полон, отказавших ячеек нет вовсе.
        #
        # Судить по одному `Percentage Used` — значит паниковать раньше времени;
        # судить по одному SMART Verified — значит не заметить износа вовсе.
        if warn and warn.group(1) != "0x00":
            disk["вердикт"] = "🔴 критическое предупреждение накопителя — бэкап немедленно"
        elif spare is not None and spare_min is not None and spare <= spare_min:
            disk["вердикт"] = "🔴 резервные блоки на исходе — диск подменяет отказавшие ячейки"
        elif used is not None and used >= 100:
            disk["вердикт"] = ("ресурс записи выработан, но резерв не тронут — "
                              "работает, держать бэкап")
        elif used is not None and used >= 80:
            disk["вердикт"] = "ресурс записи на исходе"
        disk["🔴 как читать"] = (
            "«Израсходовано» — счётчик записи по мерке производителя, он может "
            "перевалить за 100 % и это не отказ. Настоящий признак умирания — "
            "падение резерва блоков ниже порога. Отказ SSD всё равно приходит "
            "внезапно: бэкап важнее любого счётчика.")
    else:
        disk["🔴 оговорка"] = ("износ ячеек не измерен: нет smartctl. "
                              "SMART Verified означает «не отказал», а не «не изношен». "
                              "Поставить: brew install smartmontools")
    items.append(disk)

    # ── То, что НЕ оценивается. Названо явно, чтобы молчание не читалось
    #    как «здесь всё хорошо» (`71` §7ж: не проверял ≠ работает).
    unknown = ["материнская плата", "клавиатура", "экран и подсветка",
               "разъёмы и шлейфы", "динамики", "камера"]
    fans = fans_and_temps()

    return {
        "узлы": items,
        "вентиляторы": fans,
        "не_оценивается": unknown,
        "🔴 главное": "Отказ электроники — событие, а не износ: приходит внезапно "
                      "и по счётчикам не предсказывается. Оценён только измеримый "
                      "ресурс; отсутствие тревоги здесь НЕ означает исправности "
                      "неизмеренного.",
    }


def selftest_protection() -> bool:
    """Канарейка порогов защиты: различают ли они включённое и выключенное.

    🔴 Проверка, которую нельзя провалить, — не проверка (`71` §7в). Поэтому
    оба направления: на выключенном FileVault тревога обязана быть, на
    включённом — обязана отсутствовать. Одного первого мало: проверка,
    кричащая всегда, тоже «ловит».

    Проверяется `diagnose()` — та самая функция, что работает на живом снимке,
    а не её копия: иначе канарейка сторожила бы саму себя.
    """
    пусто = {"нагрузка": {}, "память": {}, "диск": {"smart": {}},
             "батарея": {}, "бэкап": {}}

    выкл = dict(пусто, прошивка={"filevault": "выключен", "sip": "включён",
                                 "gatekeeper": "включён",
                                 "автообновление_критические": "вкл"})
    if not any("FileVault" in b for b in diagnose(выкл)):
        print("🔴 канарейка: выключенный FileVault НЕ поднял тревогу", file=sys.stderr)
        return False

    вкл = dict(пусто, прошивка={"filevault": "включён", "sip": "включён",
                                "gatekeeper": "включён",
                                "автообновление_критические": "вкл"})
    if any("FileVault" in b or "SIP" in b for b in diagnose(вкл)):
        print("🔴 канарейка: тревога при исправной защите", file=sys.stderr)
        return False

    # «недоступно» — не «выключено». Машина без прав на чтение настройки
    # не должна выглядеть незащищённой: это ложная тревога, а она обучает
    # не читать вывод.
    # 🔴 «Недоступно» — не «выключено», и «данных нет» — не «сломано».
    # Машина, где настройку не удалось прочитать, не должна выглядеть
    # незащищённой: ложная тревога обучает не читать вывод.
    # Эта проверка на первом же прогоне нашла настоящий дефект — пустой
    # снимок выдавал «SMART диска: None».
    нет = dict(пусто, прошивка={"filevault": "недоступно", "sip": "недоступно",
                                "gatekeeper": "недоступно",
                                "автообновление_критические": "недоступно"})
    шум = diagnose(нет)
    if шум:
        print(f"🔴 канарейка: ложная тревога на снимке без данных: {шум}",
              file=sys.stderr)
        return False
    return True


def collect(measure_net: bool = False, full_serial: bool = False,
            check_updates: bool = False) -> dict:
    snap = {
        "снято": datetime.now().isoformat(timespec="seconds"),
        "здоровье": health(),
        "бэкап": backup_state(),
        "по_ресурсам": top_by_resource(),
        "скрытая_нагрузка": hidden_load(),
        "vpn": vpn_state(),
        "открытые_приложения": open_apps(),
        "железо": hardware(),
        "прошивка": firmware(full_serial, check_updates),
        "нагрузка": load(),
        "память": memory(),
        "диск": disks(),
        "батарея": battery(),
        "сеть": network(measure_net),
        "топ_процессов": top_processes(),
    }
    snap["перейдено_порогов"] = diagnose(snap)
    return snap


def render(snap: dict) -> None:
    h, l, m, d, b, n = (snap["железо"], snap["нагрузка"], snap["память"],
                        snap["диск"], snap["батарея"], snap["сеть"])
    print(f"╭─ {h['модель']} · {h['идентификатор']} · macOS {h['macos']}")
    print(f"│  {h['процессор']} · {h['ядер']} ядер · {h['память_гб']} ГБ RAM · {h['архитектура']}")
    print("╰─")
    # 🔴 Load average объясняется прямо в выводе: владелец спросил, что это,
    # и справочник в другом файле он в этот момент читать не станет.
    lp = l["load_на_ядро"]
    if isinstance(lp, (int, float)):
        чтение = ("простаивает" if lp < 0.7 else
                  "нормально" if lp < 1.0 else
                  "очередь копится" if lp < 2.0 else
                  "🔴 машина не успевает")
    else:
        чтение = ""
    print(f"\nНАГРУЗКА   load {l['load_1_5_15']} → {l['load_на_ядро']} на ядро · {чтение}")
    print(f"           (load — сколько задач ЖДЁТ выполнения; три числа = "
          f"среднее за 1, 5 и 15 мин.")
    print(f"            делить на {l['ядер']} ядра: до 1.0 — успевает, выше — очередь)")
    if l["cpu_user_sys_idle"] != "недоступно":
        u, s, i = l["cpu_user_sys_idle"]
        print(f"           CPU: {u}% пользовательские · {s}% система · {i}% простой")
    print(f"ПАМЯТЬ     свободно {m['свободно_мб']} МБ · сжато {m['сжато_мб']} МБ · "
          f"своп {m['своп_использован_мб']} МБ")
    print(f"ДИСК       {d['модель']} · занято {d['занято_гб']} ГБ, свободно {d['свободно_гб']} ГБ "
          f"({d['свободно_проц']} %) · SMART {d['smart']['состояние']}")
    print(f"БАТАРЕЯ    здоровье {b['здоровье_проц']} % · {b['циклов']} циклов · "
          f"{b['температура_батареи_c']} °C · питание от {b['питание']}")
    print(f"СЕТЬ       {n['интерфейс']} · {n['ip']} · пинг {n['пинг_мс']} мс")

    # 🔴 VPN печатается ЦЕНОЙ, а не флажком «включён». Владелец живёт в России
    # и без туннеля не работает — вопрос не «включать ли», а «сколько берёт».
    v = snap.get("vpn") or {}
    if v.get("активен") == "да":
        procs = v.get("процессы") or []
        if procs:
            p0 = procs[0]
            print(f"VPN        🟢 активен · {v['маршрут_через']} · "
                  f"{p0['процесс']} держит {p0['доля_ядра_проц']} % ядра "
                  f"(сейчас {p0['сейчас_проц']:.0f} %)")
            print(f"           за {p0['работает']} работы съел {p0['время_cpu']} "
                  f"процессорного времени")
        else:
            print(f"VPN        🟢 активен · {v['маршрут_через']} · "
                  f"процесс-держатель не опознан")
        t = v.get("трафик") or {}
        if t.get("🔴 ноль на туннеле"):
            print(f"           трафик туннеля 0 — клиент через NetworkExtension, "
                  f"счётчики utun его не видят")
        else:
            print(f"           туннель: принято {t.get('туннели_принято','?')} · "
                  f"отдано {t.get('туннели_отдано','?')}")
    elif v:
        print(f"VPN        выключен · маршрут через {v.get('маршрут_через','?')}")
    for k in ("скачивание", "отдача", "скорость"):
        if k in n:
            print(f"           {k}: {n[k]}")
    tr = snap.get("по_ресурсам", {})
    if tr:
        точно = "sudo" in tr.get("источник", "")
        if точно:
            вт = tr.get("мощность_пакета_вт")
            загл = f"\nЭНЕРГИЯ · {вт} Вт пакет" if вт else "\nЭНЕРГИЯ"
            ч = tr.get("частота_от_номинала_проц")
            if ч:
                загл += f" · частота {ч} % номинала"
            print(загл)
            for r in tr.get("по_энергии", [])[:6]:
                print(f"   {r['энергия']:>10.1f}  {r['имя'][:38]}")
            for key, title in (("диск_по_процессам", "ДИСК ПО ПРОЦЕССАМ"),
                               ("сеть_по_процессам", "СЕТЬ ПО ПРОЦЕССАМ")):
                rows = tr.get(key)
                if rows:
                    print(f"\n{title}")
                    for line in rows[:6]:
                        print(f"   {line[:88]}")
        else:
            print("\nЭНЕРГИЯ (приближённо: накопленное время CPU)")
            for r in tr.get("по_времени_cpu", []):
                print(f"   {r['время_cpu']:>10}  {r['cpu']:>5.1f}%  {r['имя'][:38]}")
            print(f"   🔴 {tr.get('🔴 оговорка', '')}")

    print("\nТОП ПО CPU")
    for p in snap["топ_процессов"]:
        print(f"   {p['cpu']:>5.1f}%  {p['rss_мб']:>5} МБ  {p['имя'][:44]}")
    # 🔴 Прошивка и базовое ПО. Раздел печатается ВСЕГДА, а не по флагу:
    # выключенный FileVault или SIP — состояние, о котором узнают тогда, когда
    # уже поздно, и молчащая строка здесь ничем не лучше отсутствующей.
    f = snap.get("прошивка", {})
    if f:
        # Раздел печатается здесь, а кроссплатформенный разбор живёт
        # в `firmware_probe.py`: на macOS оба дают одно и то же, на чужой
        # платформе работает только второй. Общего кода нет намеренно —
        # тут раздел с порогами, там снимок; сливать их значило бы тащить
        # пороги macOS на Linux, где они не проверены.
        print("\nПРОШИВКА И БАЗОВОЕ ПО")
        print(f"   macOS        {f['macos']} · ядро {f['ядро']}")
        print(f"   прошивка EFI {f['прошивка_efi']}")
        print(f"                (аналог BIOS; настроек в ней нет — политики задаёт macOS)")
        print(f"   загрузчик    {f['загрузчик']}")
        if f["чип_безопасности"] != "недоступно":
            print(f"   {f['чип_безопасности']} · прошивка {f['прошивка_чипа']}")
        marks = {"включён": "🟢", "выключен": "🔴", "недоступно": "·"}
        print(f"   SIP {marks.get(f['sip'], '·')} {f['sip']}"
              f" · Gatekeeper {marks.get(f['gatekeeper'], '·')} {f['gatekeeper']}"
              f" · FileVault {marks.get(f['filevault'], '·')} {f['filevault']}")
        print(f"   XProtect {f['xprotect']} · автообновления: скачивание "
              f"{f['автообновление_скачивание']}, критические "
              f"{f['автообновление_критические']}")
        print(f"   машина {f['серийный']} · блокировка активации "
              f"{f['блокировка_активации']}")
        if f["установщики_macos"]:
            for i in f["установщики_macos"]:
                print(f"   установщик   {i['имя']} — {i['мб']} МБ")
        else:
            print("   установщиков macOS на диске нет")
        upd = f.get("обновления", "")
        if upd and not upd.startswith("не спрашивались"):
            print(f"   обновления   {upd}")

        print("\n   не читается без Recovery: политика Secure Boot чипа T2 (`bputil`)")
        print("   доступные обновления — только по `--updates` (сеть, десятки секунд)")

    h = snap.get("здоровье", {})
    if h:
        print("\nИЗНОС КОМПОНЕНТОВ")
        for u in h["узлы"]:
            if u["узел"] == "батарея":
                print(f"   батарея      износ {u['износ_проц']} % · "
                      f"{u['израсходовано_ресурса_проц']} % ресурса циклов · "
                      f"{u['вердикт']}")
                print(f"                macOS: {u['состояние_по_macos']} · "
                      f"осталось ~{u['остаток_циклов']} циклов "
                      f"(≈{u['оценка_месяцев']} мес при 0.7 цикла/день)")
            else:
                extra = (f" · износ ячеек {u['израсходовано_ресурса_проц']} %"
                         if "израсходовано_ресурса_проц" in u else "")
                print(f"   накопитель   SMART {u['smart']} · {u['вердикт']}{extra}")
        f = h.get("вентиляторы")
        if isinstance(f, dict):
            if f.get("источник", "").startswith("powermetrics"):
                print(f"   вентиляторы  источник: {f['источник']}")
                for line in (f.get("вентиляторы") or [])[:4]:
                    print(f"                {line}")
                for k, v in (f.get("температуры") or {}).items():
                    print(f"                {k}: {v}")
            else:
                print(f"   вентиляторы  недоступно без sudo · "
                      f"батарея {f.get('температура_батареи_c', '?')} °C")
                print(f"                → {f.get('как_получить', '')}")
        else:
            print(f"   вентиляторы  {f}")
        b = snap.get("бэкап", {})
        if b:
            print(f"   бэкап        {b['последняя_копия']}"
                  + (f" ({b['дней_без_бэкапа']} дн назад)"
                     if isinstance(b.get("дней_без_бэкапа"), int) else "")
                  + f" · назначение: {b['назначение']}")
        print(f"   🔴 НЕ оценивалось: {', '.join(h['не_оценивается'])}")
        print("      Отказ электроники — событие, а не износ: по счётчикам")
        print("      не предсказывается. Тишина здесь ≠ исправность.")

    hl = snap.get("скрытая_нагрузка", {})
    procs = hl.get("процессы", [])
    if procs:
        print(f"\nСКРЫТАЯ НАГРУЗКА · доля от аптайма {hl.get('аптайм_ч', '?')} ч")
        print("   🔴 Мгновенный % обманывает: службы работают волнами.")
        print("      Доля от аптайма — не обманывает.\n")
        for r in procs[:8]:
            note = f"  ← {r['что_это']}" if r["что_это"] else ""
            print(f"   {r['доля_проц']:>5.1f}%  {r['время']:>11}  "
                  f"сейчас {r['сейчас']:>5.1f}%  {r['имя'][:26]}{note}")
        actions = [r for r in procs if r["что_делать"]]
        if actions:
            print("\n   ЧТО ДЕЛАТЬ:")
            for r in actions[:5]:
                print(f"     · {r['имя']}: {r['что_делать']}")

    apps = snap.get("открытые_приложения", [])
    if apps:
        print("\nОТКРЫТЫЕ ПРИЛОЖЕНИЯ")
        for a in apps:
            pl = f" ({a['процессов']} проц.)" if a["процессов"] > 1 else ""
            print(f"   {a['память_мб']:>6} МБ  {a['cpu']:>5.1f}%  {a['имя'][:30]}{pl}")

    bad = snap["перейдено_порогов"]
    print()
    if bad:
        print(f"🔴 ПЕРЕЙДЕНО ПОРОГОВ: {len(bad)}")
        for line in bad:
            print(f"   · {line}")
    else:
        print("🟢 все пороги в норме — зелёное молчит, подробности в --json")


def watch(interval: float = 2.0) -> int:
    """Живая строка состояния — как статус-бар iTerm, но с нашими числами.

    ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026: «а он же будет уметь делать, как iTerm вон
    показывает справа вверху всякие показатели устройства?»

    🔴 РАЗНИЦА ЖАНРОВ, И ОНА НЕ КОСМЕТИЧЕСКАЯ. Полный срез (`collect`) снимает
    железо, SMART и батарею — это секунды работы и десятки запусков утилит.
    Опрашивать их каждые две секунды бессмысленно: износ SSD не меняется
    за две секунды, а нагрузка меняется постоянно.
    Поэтому здесь снимаются ТОЛЬКО быстрые показатели, а медленные —
    один раз при старте и показываются как неподвижная шапка.
    """
    import shutil as _sh
    fixed = {"hw": hardware(), "health": health()}
    hw, dh = fixed["hw"], fixed["health"]
    disk_item = next((u for u in dh["узлы"] if u["узел"] == "накопитель"), {})
    bat_item = next((u for u in dh["узлы"] if u["узел"] == "батарея"), {})

    # Счётчики сети: считаем ПРИРОСТ между тиками, а не абсолют.
    def netbytes() -> tuple[int, int]:
        out = sh(["netstat", "-ib"])
        rx = tx = 0
        seen = set()
        for line in out.splitlines()[1:]:
            f = line.split()
            if len(f) < 10 or f[0] in seen or f[0].startswith("lo"):
                continue
            seen.add(f[0])
            try:
                rx += int(f[6]); tx += int(f[9])
            except (ValueError, IndexError):
                continue
        return rx, tx

    prev = netbytes()
    print(f"\033[1m{hw['модель']} · {hw['процессор']} · {hw['память_гб']} ГБ · "
          f"macOS {hw['macos']}\033[0m")
    print(f"диск: SMART {disk_item.get('smart', '?')} · износ "
          f"{disk_item.get('израсходовано_ресурса_проц', '?')} % · резерв "
          f"{disk_item.get('резерв_блоков_проц', '?')} %   |   батарея: "
          f"{bat_item.get('износ_проц', '?')} % износа, "
          f"{bat_item.get('остаток_циклов', '?')} циклов")
    print("─" * min(_sh.get_terminal_size().columns, 100))
    print("Ctrl+C — выход\n")
    try:
        while True:
            l, m, d = load(), memory(), disks()
            rx, tx = netbytes()
            drx = max(rx - prev[0], 0) / interval / 1024
            dtx = max(tx - prev[1], 0) / interval / 1024
            prev = (rx, tx)
            cpu = l["cpu_user_sys_idle"]
            busy = round(100 - cpu[2], 1) if cpu != "недоступно" else "?"
            # \r + \033[K — перерисовка строки на месте, без прокрутки
            print(f"\r\033[K cpu {busy:>5} %  ·  load {l['load_на_ядро']:>5}/ядро  ·  "
                  f"память {m['свободно_мб']:>5} МБ своб  ·  своп {m['своп_использован_мб']:>5} МБ  ·  "
                  f"диск {d['свободно_гб']:>5} ГБ  ·  сеть ↓{drx:6.1f} ↑{dtx:6.1f} КБ/с",
                  end="", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n")
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# ЖУРНАЛ НАБЛЮДЕНИЙ
#
# 🔴 ЗАКАЗ ВЛАДЕЛЬЦА 02.09.2026, дословно: «давай туда как с лабой клода каждый
# раз скилл запуская machine заносить в него лог. чтобы следить и отслеживать
# что ломает как что влияет на мое железо и нагрузку и была история».
#
# ПОЧЕМУ ЗАПИСЬ БЕЗ ФЛАГА. История, которую надо не забыть попросить, — это
# обещание, а не история (`21-revision-protocol.md` §4г: правило без исполнителя
# не исполняется). Полугодовой перегрев не был замечен ровно потому, что
# показания снимались разово и нигде не оседали: каждый замер начинался с нуля,
# и «стало хуже» сравнивать было не с чем. Поэтому строка пишется при КАЖДОМ
# запуске сама, а `--no-log` существует для случая, когда замер заведомо
# нерепрезентативен (проверка самого скрипта, чужая машина).
#
# ЧТО ЗДЕСЬ ЛЕЖИТ, А ЧТО НЕТ. CSV — только ПОКАЗАНИЯ (числа приборов).
# СОБЫТИЯ («отключили Spotlight», «поставили Docker») живут в HISTORY.md
# и пишутся человеком: машина не знает, что именно ты сделал, а без этого
# ряд чисел не объясняет сам себя. Разделение то же, что у лаборатории
# расхода: `measurements.csv` (замеры) против `hypothesis.md` (модель).
# ─────────────────────────────────────────────────────────────────────────────

OBS_DIR = Path(__file__).resolve().parent.parent / "observations"
OBS_CSV = OBS_DIR / "measurements.csv"

OBS_COLUMNS = [
    "снято", "аптайм_ч", "ядер", "load1", "load5", "load15", "load_на_ядро",
    "cpu_user", "cpu_sys", "cpu_idle", "память_свободно_мб", "сжато_мб",
    "своп_мб", "диск_свободно_гб", "диск_свободно_проц", "батарея_здоровье_проц",
    "батарея_циклов", "батарея_темп_c", "питание", "smart", "spotlight",
    "порогов_перейдено", "vpn", "vpn_проц", "топ1", "топ2", "топ3",
    "фон1", "фон2", "фон3", "пометка",
]

# 🔴 Две разные колонки, и путать их нельзя — на этом сгорела диагностика
# перегрева 02.09.2026. «топN» — мгновенный %CPU: кто грузит машину ПРЯМО
# СЕЙЧАС. «фонN» — доля от аптайма: кто сожрал процессор ЗА ВСЁ ВРЕМЯ работы.
# Фоновая служба между волнами показывает честный ноль в первой колонке
# и 20 % во второй; смотреть надо на вторую.


def _spotlight_state() -> str:
    """Включён ли индекс Spotlight — он оказался главным едоком 02.09.2026."""
    out = sh(["mdutil", "-a", "-s"], timeout=15)
    if not out:
        return "неизвестно"
    if "Indexing enabled" in out:
        return "on"
    if "Indexing disabled" in out:
        return "off"
    return "неизвестно"


def _uptime_hours() -> float:
    m = re.search(r"sec\s*=\s*(\d+)", sh(["sysctl", "-n", "kern.boottime"]))
    return round((time.time() - int(m.group(1))) / 3600, 1) if m else ""


def observation_row(snap: dict, note: str = "") -> dict:
    """Плоская строка показаний из снимка. Недоступное остаётся пустым."""
    def g(d, *keys, default=""):
        for k in keys:
            if not isinstance(d, dict):
                return default
            d = d.get(k, default)
        return d if not isinstance(d, (dict, list)) else default

    l, m, d, b = (snap.get("нагрузка", {}), snap.get("память", {}),
                  snap.get("диск", {}), snap.get("батарея", {}))
    la = l.get("load_1_5_15")
    la = la if isinstance(la, list) and len(la) == 3 else ["", "", ""]
    cpu = l.get("cpu_user_sys_idle")
    cpu = cpu if isinstance(cpu, list) and len(cpu) == 3 else ["", "", ""]
    top = snap.get("топ_процессов") or []

    row = {
        "снято": snap.get("снято", ""),
        "аптайм_ч": _uptime_hours(),
        "ядер": l.get("ядер", ""),
        "load1": la[0], "load5": la[1], "load15": la[2],
        "load_на_ядро": l.get("load_на_ядро", ""),
        "cpu_user": cpu[0], "cpu_sys": cpu[1], "cpu_idle": cpu[2],
        "память_свободно_мб": m.get("свободно_мб", ""),
        "сжато_мб": m.get("сжато_мб", ""),
        "своп_мб": m.get("своп_использован_мб", ""),
        "диск_свободно_гб": d.get("свободно_гб", ""),
        "диск_свободно_проц": d.get("свободно_проц", ""),
        "батарея_здоровье_проц": b.get("здоровье_проц", ""),
        "батарея_циклов": b.get("циклов", ""),
        "батарея_темп_c": b.get("температура_батареи_c", ""),
        "питание": b.get("питание", ""),
        "smart": g(d, "smart", "состояние"),
        "spotlight": _spotlight_state(),
        "порогов_перейдено": len(snap.get("перейдено_порогов") or []),
        "vpn": (snap.get("vpn") or {}).get("активен", ""),
        # доля самого дорогого VPN-процесса — цена туннеля одной колонкой
        "vpn_проц": next((p.get("доля_ядра_проц") for p in
                          (snap.get("vpn") or {}).get("процессы", [])), ""),
        "пометка": note,
    }
    for i in range(3):
        p = top[i] if i < len(top) else {}
        row[f"топ{i+1}"] = (f"{p.get('имя', '')}:{p.get('cpu', '')}%"
                            if isinstance(p, dict) and p.get("имя") else "")

    # Фоновые пожиратели — по ДОЛЕ ОТ АПТАЙМА, а не по мгновенному проценту.
    fon = (snap.get("скрытая_нагрузка") or {}).get("процессы") or []
    for i in range(3):
        p = fon[i] if i < len(fon) else {}
        row[f"фон{i+1}"] = (f"{p.get('имя', '')}:{p.get('доля_проц', '')}%"
                            if isinstance(p, dict) and p.get("имя") else "")
    return row


def _migrate_columns() -> None:
    """Заголовок журнала отстал от списка колонок — дописать недостающие.

    🔴 НАЙДЕНО НА ЖИВОЙ ЗАПИСИ 03.09.2026, в тот же час, когда добавились
    колонки `vpn` и `vpn_проц`. `DictWriter` пишет значения в порядке
    `fieldnames`, а заголовок в файле остался прежним, 29-колоночным:
    строка легла со сдвигом, и пометка «VPN-разбор» оказалась в поле `топ1`
    как `mds_stores:7.1%`.

    Дефект тихий и того же класса, что вся эта вахта: файл читается,
    выглядит правдой, и правда в нём сдвинута на две позиции. Заметить это
    можно только глазами на конкретной строке — ни одна проверка не ругалась.

    Поэтому миграция автоматическая: расширение набора показаний — нормальная
    эволюция журнала, а не событие, ради которого вахта лезет править CSV
    руками. Старые строки получают пустые значения в новых колонках — это
    честно: тогда не мерили.
    """
    if not OBS_CSV.is_file():
        return
    try:
        with OBS_CSV.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
            head = list(rows[0].keys()) if rows else []
    except OSError:
        return
    if head == OBS_COLUMNS:
        return
    # Порядок колонок мог не только дополниться, но и перемешаться —
    # DictWriter разложит значения по именам, а не по позициям.
    try:
        with OBS_CSV.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=OBS_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in OBS_COLUMNS})
        added = [c for c in OBS_COLUMNS if c not in head]
        if added:
            print(f"  · журнал расширен: +{', '.join(added)} "
                  f"(прежние {len(rows)} строк сохранены)")
    except OSError as e:
        print(f"🟡 журнал не мигрирован: {e}", file=sys.stderr)


def log_observation(snap: dict, note: str = "") -> Path | None:
    """Дописать строку показаний. Тихо отказывает: журнал не важнее замера."""
    try:
        OBS_DIR.mkdir(parents=True, exist_ok=True)
        _migrate_columns()
        new = not OBS_CSV.is_file()
        with OBS_CSV.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=OBS_COLUMNS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(observation_row(snap, note))
        return OBS_CSV
    except OSError as e:
        print(f"🟡 журнал не пополнен: {e}", file=sys.stderr)
        return None


def show_history(limit: int = 12) -> int:
    """История замеров: что менялось от раза к разу.

    🔴 Печатает ИЗМЕНЕНИЕ, а не только значения. Ряд одинаковых чисел
    не читается глазами — а скачок load с 2 до 7 или своп, выросший вдвое,
    виден сразу. Ровно этого не хватало, чтобы заметить перегрев за полгода.
    """
    if not OBS_CSV.is_file():
        print("Журнал пуст: ни одного замера ещё не записано.\n"
              "Он пополняется сам при каждом запуске machine_probe.py.")
        return 0
    with OBS_CSV.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("Журнал заведён, но пуст.")
        return 0

    rows = rows[-limit:]
    print(f"Журнал наблюдений · {len(rows)} последних замеров "
          f"(всего в файле — считает `wc -l {OBS_CSV.name}`)\n")
    hdr = (f"{'когда':<17}{'load':>6}{'/ядро':>7}{'своп МБ':>9}"
           f"{'память МБ':>11}{'диск ГБ':>9}  {'spot':<5}{'порог':>6}  пометка")
    print(hdr)
    print("─" * len(hdr))

    def f(v, prev, fmt="{}", better_lower=True):
        """Значение со стрелкой изменения к предыдущему замеру."""
        try:
            cur, old = float(v), float(prev)
        except (TypeError, ValueError):
            return fmt.format(v or "—")
        mark = ""
        if abs(cur - old) > 1e-9:
            up = cur > old
            bad = up if better_lower else not up
            mark = ("↑" if up else "↓") + ("!" if bad and abs(cur - old) / max(old, 1e-9) > 0.5 else "")
        return fmt.format(v) + mark

    prev = {}
    for r in rows:
        when = (r.get("снято") or "")[5:16].replace("T", " ")
        print(f"{when:<17}"
              f"{f(r.get('load1'), prev.get('load1')):>6}"
              f"{f(r.get('load_на_ядро'), prev.get('load_на_ядро')):>7}"
              f"{f(r.get('своп_мб'), prev.get('своп_мб')):>9}"
              f"{f(r.get('память_свободно_мб'), prev.get('память_свободно_мб'), better_lower=False):>11}"
              f"{f(r.get('диск_свободно_гб'), prev.get('диск_свободно_гб'), better_lower=False):>9}"
              f"  {(r.get('spotlight') or '—'):<5}"
              f"{(r.get('порогов_перейдено') or '0'):>6}  "
              f"{(r.get('пометка') or '')[:40]}")
        prev = r

    print("\n  ↑/↓ — изменение к предыдущему замеру, «!» — более чем в полтора раза.")
    print(f"  Показания — {OBS_CSV}")
    print(f"  События («что сделали») — {OBS_DIR / 'HISTORY.md'}, пишутся человеком:")
    print("  ряд чисел не объясняет сам себя, если не записано, что между ними произошло.")
    return 0


def main() -> int:
    if platform.system() != "Darwin":
        # 🔴 ОТКАЗ ОСТАЁТСЯ, НО ПЕРЕСТАЛ БЫТЬ ТУПИКОМ (03.09.2026).
        # Нагрузка, память, диск и батарея здесь снимаются командами macOS
        # (`vm_stat`, `pmset`, `system_profiler`) — на Linux и Windows их нет,
        # и догадываться о значениях нельзя. Но ПРОШИВКА и базовое ПО
        # кроссплатформенны, и заказ владельца был именно про них.
        #
        # Поэтому: отказ с ненулевым кодом — и рядом рабочий инструмент,
        # а не одна строка «не поддерживается». Тупик хуже отказа: он
        # не оставляет следующего шага.
        print("🔴 Полный срез снимает состояние macOS; здесь система "
              f"{platform.system()}.", file=sys.stderr)
        print("   Прошивка, железо и базовое ПО читаются везде:", file=sys.stderr)
        print(f"     python3 {Path(__file__).parent / 'firmware_probe.py'}",
              file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description="Снимок состояния Mac")
    ap.add_argument("--json", action="store_true", help="выдать JSON вместо текста")
    ap.add_argument("--selftest", action="store_true",
                    help="канарейка: различают ли пороги защиты состояния")
    ap.add_argument("--updates", action="store_true",
                    help="спросить доступные обновления macOS (сеть, десятки секунд)")
    ap.add_argument("--full-serial", action="store_true",
                    help="показать серийный номер целиком (по умолчанию маскирован)")
    ap.add_argument("--net", action="store_true",
                    help="замерить скорость сети (networkQuality, ~15 с)")
    ap.add_argument("--watch", action="store_true",
                    help="живая строка состояния, как статус-бар iTerm")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="период обновления для --watch, секунд (по умолчанию 2)")
    ap.add_argument("--note", default="",
                    help="пометка к замеру: что сейчас происходит "
                         "(«после отключения Spotlight», «идёт сборка»)")
    ap.add_argument("--no-log", action="store_true",
                    help="не писать строку в журнал наблюдений "
                         "(замер заведомо нерепрезентативен)")
    ap.add_argument("--history", nargs="?", type=int, const=12, default=None,
                    metavar="N", help="показать N последних замеров с изменениями")
    args = ap.parse_args()
    if args.history is not None:
        return show_history(args.history)
    if args.watch:
        # 🔴 --watch не пишет: он снимает показания каждые две секунды,
        # и журнал за час работы получил бы 1800 строк шума вместо истории.
        return watch(args.interval)
    if args.selftest:
        ok = selftest_protection()
        print("канарейка порогов защиты: " + ("🟢 зелёная" if ok else "🔴 красная"))
        return 0 if ok else 1

    snap = collect(args.net, args.full_serial, args.updates)
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        render(snap)
    if not args.no_log:
        path = log_observation(snap, args.note)
        if path and not args.json:
            print(f"\n  · замер записан в журнал: {path.name} "
                  f"(история — `--history`)")
    return 1 if snap["перейдено_порогов"] else 0


if __name__ == "__main__":
    sys.exit(main())
