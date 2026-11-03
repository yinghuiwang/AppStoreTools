"""Read and write the local review-status schedule file."""

from __future__ import annotations

import errno
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo, available_timezones

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.11+ has tomllib
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # type: ignore[assignment]


_ID_RE = re.compile(r"^[0-9a-f]{8}$")
_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
WATCH_APP_STORE = "app_store"
WATCH_TESTFLIGHT = "testflight"
VALID_WATCH = frozenset({WATCH_APP_STORE, WATCH_TESTFLIGHT})
WATCH_LABELS = {
    WATCH_APP_STORE: "App Store 版本审核",
    WATCH_TESTFLIGHT: "TestFlight 外部组版本审核",
}
_OPTIONAL_KEYS = frozenset({"watch", "last_notified_result"})
_BASE_KEYS = frozenset(
    {
        "id",
        "profile",
        "enabled",
        "kind",
        "time",
        "timezone",
        "next_run_at",
        "last_run_at",
        "last_error",
        "last_result",
    }
)


class ScheduleError(Exception):
    def __init__(self, code: str, **params: object) -> None:
        self.code = code
        self.params = params
        super().__init__(code)


class ScheduleCorruptError(ScheduleError):
    def __init__(self, **params: object) -> None:
        super().__init__("corrupt", **params)


class ScheduleLockTimeout(ScheduleError):
    def __init__(self, **params: object) -> None:
        super().__init__("lock_timeout", **params)


class ScheduleLockBusy(ScheduleError):
    def __init__(self, **params: object) -> None:
        super().__init__("lock_busy", **params)


class ScheduleNotFound(ScheduleError):
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__("not_found", task_id=task_id)


class ScheduleTask:
    def __init__(
        self,
        id: str,
        profile: str,
        enabled: bool,
        kind: str,
        time: str,
        timezone: str,
        next_run_at: str,
        last_run_at: str,
        last_error: str,
        last_result: str,
        interval_hours: Optional[int] = None,
        weekdays: Optional[list] = None,
        watch: str = WATCH_APP_STORE,
        last_notified_result: str = "",
    ) -> None:
        self.id = id
        self.profile = profile
        self.enabled = enabled
        self.kind = kind
        self.time = time
        self.timezone = timezone
        self.next_run_at = next_run_at
        self.last_run_at = last_run_at
        self.last_error = last_error
        self.last_result = last_result
        self.interval_hours = interval_hours
        self.weekdays = weekdays
        self.watch = watch if watch in VALID_WATCH else WATCH_APP_STORE
        self.last_notified_result = last_notified_result or ""


def default_schedule_path() -> Path:
    return Path.home() / ".config" / "asc" / "schedules.toml"


def load_tasks(schedule_path: Path) -> list:
    if not schedule_path.exists():
        return []
    try:
        text = schedule_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ScheduleCorruptError() from exc
    data = _parse_document(text)
    if not data:
        return []
    if set(data) != {"tasks"}:
        raise ScheduleCorruptError()
    raw_tasks = data["tasks"]
    if not isinstance(raw_tasks, list):
        raise ScheduleCorruptError()
    loaded = []
    seen: set = set()
    for item in raw_tasks:
        loaded.append(_parse_task(item, seen))
    return loaded


def save_tasks(schedule_path: Path, tasks: list) -> None:
    parent = schedule_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    payload = _render_tasks(tasks)
    fd, raw_name = tempfile.mkstemp(prefix=".schedules.", suffix=".tmp", dir=str(parent))
    tmp_path = Path(raw_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_path, schedule_path)
    except BaseException:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def new_task_id(existing: set, rng=None) -> str:
    choose = rng if rng is not None else (lambda: uuid.uuid4().hex[:8])
    while True:
        candidate = choose()
        if candidate not in existing:
            return candidate


def _flock_module():
    """Return fcntl when it imports, otherwise msvcrt. Branch on the import, not the OS name."""
    try:
        import fcntl
    except ImportError:
        fcntl = None
    if fcntl is not None and hasattr(fcntl, "flock"):
        return fcntl
    try:
        import msvcrt
    except ImportError:
        return None
    if hasattr(msvcrt, "locking"):
        return msvcrt
    return None


def _lock_kind(module) -> str:
    if module is None:
        return "none"
    if hasattr(module, "flock") and hasattr(module, "LOCK_EX") and hasattr(module, "LOCK_NB"):
        return "fcntl"
    if hasattr(module, "locking") and hasattr(module, "LK_NBLCK"):
        return "msvcrt"
    return "none"


def _acquire_lock(module, handle) -> None:
    if _lock_kind(module) == "fcntl":
        module.flock(handle.fileno(), module.LOCK_EX | module.LOCK_NB)
        return
    handle.seek(0)
    module.locking(handle.fileno(), module.LK_NBLCK, 1)


def _release_lock(module, handle) -> None:
    if _lock_kind(module) == "fcntl":
        module.flock(handle.fileno(), module.LOCK_UN)
        return
    handle.seek(0)
    module.locking(handle.fileno(), module.LK_UNLCK, 1)


@contextmanager
def schedule_lock(schedule_path: Path, *, blocking: bool, timeout: float = 30) -> Iterator[None]:
    lock_mod = _flock_module()
    if _lock_kind(lock_mod) == "none":
        raise ScheduleError("fcntl_unavailable")
    parent = schedule_path.parent
    if not parent.exists():
        if not blocking:
            raise ScheduleLockBusy()
        parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(schedule_path) + ".lock")
    handle = lock_path.open("a+")
    held = False
    try:
        if blocking:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    _acquire_lock(lock_mod, handle)
                    held = True
                    break
                except (BlockingIOError, OSError) as exc:
                    if not _lock_busy(exc):
                        raise
                    if time.monotonic() >= deadline:
                        raise ScheduleLockTimeout()
                    time.sleep(0.05)
        else:
            try:
                _acquire_lock(lock_mod, handle)
                held = True
            except (BlockingIOError, OSError) as exc:
                if _lock_busy(exc):
                    raise ScheduleLockBusy()
                raise
        yield
    finally:
        try:
            if held:
                _release_lock(lock_mod, handle)
        finally:
            handle.close()


def _lock_busy(exc: BaseException) -> bool:
    if isinstance(exc, BlockingIOError):
        return True
    err = getattr(exc, "errno", None)
    return err in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES)


def _parse_document(text: str) -> dict:
    if tomllib is None:
        raise ScheduleCorruptError()
    try:
        data = tomllib.loads(text)
    except Exception as exc:
        raise ScheduleCorruptError() from exc
    if not isinstance(data, dict):
        raise ScheduleCorruptError()
    return data


def _parse_task(item: object, seen: set) -> ScheduleTask:
    if not isinstance(item, dict):
        raise ScheduleCorruptError()
    kind = item.get("kind")
    expected = _expected_keys(kind)
    keys = set(item)
    if expected is None or not expected <= keys or keys - expected - _OPTIONAL_KEYS:
        raise ScheduleCorruptError()
    task_id = _require_id(item["id"], seen)
    profile = _require_text(item["profile"])
    enabled = item["enabled"]
    if not isinstance(enabled, bool):
        raise ScheduleCorruptError()
    clock = _require_text(item["time"])
    if _TIME_RE.fullmatch(clock) is None:
        raise ScheduleCorruptError()
    timezone_name = _require_timezone(item["timezone"])
    next_run_at = _require_timestamp(item["next_run_at"], allow_empty=False)
    last_run_at = _require_timestamp(item["last_run_at"], allow_empty=True)
    last_error = _require_text(item["last_error"])
    last_result = _require_text(item["last_result"])
    last_notified_result = _parse_last_notified_result(item)
    interval_hours = None
    weekdays = None
    if kind == "interval":
        interval_hours = _require_interval_hours(item["interval_hours"])
    elif kind == "weekly":
        weekdays = _require_weekdays(item["weekdays"])
    return ScheduleTask(
        id=task_id,
        profile=profile,
        enabled=enabled,
        kind=str(kind),
        time=clock,
        timezone=timezone_name,
        next_run_at=next_run_at,
        last_run_at=last_run_at,
        last_error=last_error,
        last_result=last_result,
        interval_hours=interval_hours,
        weekdays=weekdays,
        watch=_parse_watch(item),
        last_notified_result=last_notified_result,
    )


def _expected_keys(kind: object) -> Optional[frozenset]:
    if kind == "daily":
        return _BASE_KEYS
    if kind == "interval":
        return _BASE_KEYS | {"interval_hours"}
    if kind == "weekly":
        return _BASE_KEYS | {"weekdays"}
    return None


def _parse_watch(item: dict) -> str:
    if "watch" not in item:
        return WATCH_APP_STORE
    value = item["watch"]
    if value not in VALID_WATCH:
        raise ScheduleCorruptError()
    return value


def _parse_last_notified_result(item: dict) -> str:
    if "last_notified_result" not in item:
        return ""
    return _require_text(item["last_notified_result"])


def require_watch(value: object) -> str:
    if value is None:
        return WATCH_APP_STORE
    if not isinstance(value, str) or value not in VALID_WATCH:
        raise ScheduleError("watch")
    return value


def _require_text(value: object) -> str:
    if not isinstance(value, str):
        raise ScheduleCorruptError()
    return value


def _require_id(value: object, seen: set) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None or value in seen:
        raise ScheduleCorruptError()
    seen.add(value)
    return value


def _require_timezone(value: object) -> str:
    if not isinstance(value, str):
        raise ScheduleCorruptError()
    try:
        ZoneInfo(value)
    except Exception as exc:
        raise ScheduleCorruptError() from exc
    return value


def _require_timestamp(value: object, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ScheduleCorruptError()
    if value == "":
        if allow_empty:
            return value
        raise ScheduleCorruptError()
    if _TIMESTAMP_RE.fullmatch(value) is None:
        raise ScheduleCorruptError()
    return value


def _require_interval_hours(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScheduleCorruptError()
    return value


def _require_weekdays(value: object) -> list:
    if not isinstance(value, list) or not value:
        raise ScheduleCorruptError()
    days = []
    for day in value:
        if isinstance(day, bool) or not isinstance(day, int) or day < 1 or day > 7:
            raise ScheduleCorruptError()
        days.append(day)
    if days != sorted(days) or len(days) != len(set(days)):
        raise ScheduleCorruptError()
    return days


def _render_tasks(tasks: list) -> str:
    if not tasks:
        return ""
    return "\n\n".join(_render_task(task) for task in tasks) + "\n"


def _render_task(task: ScheduleTask) -> str:
    lines = [
        "[[tasks]]",
        f"id = {_toml_basic(task.id)}",
        f"profile = {_toml_basic(task.profile)}",
        f"enabled = {'true' if task.enabled else 'false'}",
        f"kind = {_toml_basic(task.kind)}",
        f"watch = {_toml_basic(task.watch or WATCH_APP_STORE)}",
        f"time = {_toml_basic(task.time)}",
    ]
    if task.kind == "interval":
        lines.append(f"interval_hours = {int(task.interval_hours)}")
    elif task.kind == "weekly":
        days = ", ".join(str(int(day)) for day in (task.weekdays or []))
        lines.append(f"weekdays = [{days}]")
    lines.extend(
        [
            f"timezone = {_toml_basic(task.timezone)}",
            f"next_run_at = {_toml_basic(task.next_run_at)}",
            f"last_run_at = {_toml_basic(task.last_run_at)}",
            f"last_error = {_toml_basic(task.last_error)}",
            f"last_result = {_toml_basic(task.last_result)}",
            f"last_notified_result = {_toml_basic(task.last_notified_result or '')}",
        ]
    )
    return "\n".join(lines)


def _toml_basic(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def capture_timezone(
    *,
    environ=None,
    localtime: Optional[Path] = None,
    system: Optional[str] = None,
) -> str:
    env = os.environ if environ is None else environ
    raw = env.get("TZ", "")
    if raw is None:
        raw = ""
    name = str(raw).strip()
    if name and _zone_accepted(name):
        return name
    if _capture_uses_windows(system):
        return _timezone_from_windows()
    source = Path("/etc/localtime") if localtime is None else Path(localtime)
    resolved = os.path.realpath(source)
    marker = "zoneinfo/"
    index = resolved.rfind(marker)
    if index < 0:
        raise ScheduleError("timezone")
    found = resolved[index + len(marker) :]
    if not found or not _zone_accepted(found):
        raise ScheduleError("timezone")
    return found


def _capture_uses_windows(system: Optional[str]) -> bool:
    from asc.platform import is_windows

    return is_windows(system)


def _windows_timezone_key_name() -> str:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
    ) as key:
        value, _regtype = winreg.QueryValueEx(key, "TimeZoneKeyName")
    if isinstance(value, bytes):
        value = value.decode("utf-16-le", errors="replace")
    text = str(value).split("\x00", 1)[0].strip()
    if not text:
        raise OSError("TimeZoneKeyName is empty")
    return text


def _timezone_from_windows() -> str:
    try:
        key_name = _windows_timezone_key_name()
    except ScheduleError:
        raise
    except Exception as exc:
        raise ScheduleError("timezone") from exc
    iana = _windows_zone_to_iana(key_name)
    if not iana or not _zone_accepted(iana):
        raise ScheduleError("timezone")
    return iana


# Windows TimeZoneKeyName -> IANA. tzdata 2026.6 ships zoneinfo only, not a
# Windows map, so this table is the fallback. Rows are territory "001" entries
# from Unicode CLDR common/supplemental/windowsZones.xml and include the zones
# this project already uses (Asia/Shanghai, Europe/Berlin, America/New_York,
# UTC). A map discovered from tzdata or zoneinfo replaces this table.
_WINDOWS_ZONE_FALLBACK = {
    "Pacific Standard Time": "America/Los_Angeles",
    "Mountain Standard Time": "America/Denver",
    "Central Standard Time": "America/Chicago",
    "Eastern Standard Time": "America/New_York",
    "US Eastern Standard Time": "America/Indianapolis",
    "UTC": "Etc/UTC",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "Russian Standard Time": "Europe/Moscow",
    "India Standard Time": "Asia/Calcutta",
    "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "AUS Eastern Standard Time": "Australia/Sydney",
}


def _parse_cldr_windows_zones(text: str) -> dict:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    found = {}
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1] != "mapZone":
            continue
        if elem.attrib.get("territory") != "001":
            continue
        other = elem.attrib.get("other")
        iana = elem.attrib.get("type")
        if other and iana and other not in found:
            found[str(other)] = str(iana)
    return found


def _discover_tzdata_windows_zones() -> dict:
    """Return a Windows map shipped by tzdata or zoneinfo, when one exists."""
    module_names = (
        "tzdata.windows_zones",
        "tzdata.zoneinfo.windows_zones",
        "zoneinfo.windows_zones",
    )
    for name in module_names:
        try:
            module = __import__(name, fromlist=["WINDOWS_ZONES"])
        except ImportError:
            continue
        data = getattr(module, "WINDOWS_ZONES", None) or getattr(module, "win_tz", None)
        if isinstance(data, dict) and data:
            return {str(key): str(value) for key, value in data.items()}
    try:
        import tzdata
    except ImportError:
        return {}
    root = Path(tzdata.__file__).resolve().parent
    candidates = (
        root / "windowsZones.xml",
        root / "zoneinfo" / "windowsZones.xml",
        root / "zoneinfo" / "tzdata" / "windowsZones.xml",
    )
    for path in candidates:
        if not path.is_file():
            continue
        parsed = _parse_cldr_windows_zones(path.read_text(encoding="utf-8"))
        if parsed:
            return parsed
    return {}


@lru_cache(maxsize=1)
def _windows_zone_map() -> dict:
    discovered = _discover_tzdata_windows_zones()
    if discovered:
        return discovered
    return dict(_WINDOWS_ZONE_FALLBACK)


def _windows_zone_to_iana(key_name: str) -> str:
    name = str(key_name or "").split("\x00", 1)[0].strip()
    if not name:
        return ""
    return _windows_zone_map().get(name, "")


def require_timezone_name(value: object) -> str:
    if isinstance(value, str):
        name = value.strip()
        shown = name or value
    else:
        name = ""
        shown = value
    if not name or not _zone_accepted(name):
        raise ScheduleError("timezone_invalid", name=shown)
    return name


def list_timezones() -> list:
    names = [
        name
        for name in available_timezones()
        if not name.startswith(("posix/", "right/"))
    ]
    names.sort()
    return names


def parse_hhmm(value: str) -> tuple:
    if not isinstance(value, str) or _TIME_RE.fullmatch(value) is None:
        raise ScheduleError("time")
    hour_text, minute_text = value.split(":")
    return (int(hour_text), int(minute_text))


def parse_weekdays(value: str) -> list:
    parts = value.split(",")
    days = []
    for part in parts:
        token = part.strip()
        if re.fullmatch(r"[1-7]", token) is None:
            raise ScheduleError("weekdays")
        days.append(int(token))
    if len(days) != len(set(days)):
        raise ScheduleError("weekdays")
    return sorted(days)


def wall_slot(day: date, hour: int, minute: int, tz):
    naive = datetime(day.year, day.month, day.day, hour, minute, 0)
    aware = naive.replace(tzinfo=tz, fold=0)
    back = aware.astimezone(timezone.utc).astimezone(tz)
    same = (
        back.year,
        back.month,
        back.day,
        back.hour,
        back.minute,
        back.second,
        back.fold,
    ) == (naive.year, naive.month, naive.day, naive.hour, naive.minute, 0, 0)
    if not same:
        return None
    return aware


def next_slot(task: ScheduleTask, now: datetime) -> datetime:
    tz = ZoneInfo(task.timezone)
    start = now.astimezone(tz).date()
    hour, minute = parse_hhmm(task.time)
    anchor = hour * 60 + minute
    for offset in range(400):
        day = start + timedelta(days=offset)
        for slot_hour, slot_minute in _clock_candidates(task, day, hour, minute, anchor):
            slot = wall_slot(day, slot_hour, slot_minute, tz)
            if slot is not None and slot > now:
                return slot
    raise ScheduleError("timezone")


def format_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP_RE.fullmatch(value) is None:
        raise ScheduleCorruptError()
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleCorruptError() from exc


def due_action(next_run_at: datetime, now: datetime) -> str:
    if now - next_run_at <= timedelta(seconds=120):
        return "run"
    return "skip"


def _zone_accepted(name: str) -> bool:
    try:
        ZoneInfo(name)
    except Exception:
        return False
    return True


_AGENT_LABEL = "com.asc.schedule"
_BOOTOUT_ABSENT = (
    "No such process",
    "Could not find specified service",
    "not loaded",
    "Service not found",
    "Input/output error",
    "I/O error",
)
# ESRCH (3) and EIO (5). Modern launchctl prints EIO when the job is not loaded,
# then adds a misleading "re-run as root" hint.
_BOOTOUT_ABSENT_CODES = frozenset({3, 5})
# EIO (5) is also what bootstrap prints when the service is already loaded.
# EEXIST (17) and EINPROGRESS (37) are the older already-loaded codes.
_BOOTSTRAP_ALREADY_CODES = frozenset({5, 17, 37})
_LAUNCHCTL_ROOT_HINT = "Try re-running the command as root for richer errors."
_CRON_MARKER = "# asc-schedule"
_CRON_PREFIX = "* * * * * "
_CRON_SUFFIX = " schedule tick # asc-schedule"


def _is_asc_executable_name(name: str) -> bool:
    return name == "asc" or str(name).lower() == "asc.exe"


def _asc_file(path: Path) -> Optional[Path]:
    if not _is_asc_executable_name(path.name) or not path.is_file():
        return None
    return path.resolve()


def _find_named_asc_exe(directory: Path) -> Optional[Path]:
    if not directory.is_dir():
        return None
    exact = None
    fallback = None
    try:
        children = list(directory.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_file() or child.name.lower() != "asc.exe":
            continue
        if child.name == "asc.exe":
            exact = child
            break
        if fallback is None:
            fallback = child
    chosen = exact or fallback
    if chosen is None:
        return None
    return chosen.resolve()


def _asc_exe_for_interpreter(executable: str) -> Optional[Path]:
    parent = Path(executable).parent
    found = _find_named_asc_exe(parent)
    if found is not None:
        return found
    return _find_named_asc_exe(parent / "Scripts")


def _exe_belongs_to_interpreter(candidate: Path, executable: str) -> bool:
    try:
        resolved = candidate.resolve()
    except OSError:
        return False
    if resolved.name.lower() != "asc.exe":
        return False
    owned = _asc_exe_for_interpreter(executable)
    return owned is not None and owned == resolved


def _shebang_matches(script: Path, executable: str) -> bool:
    try:
        with script.open("rb") as handle:
            line = handle.readline(4096)
    except OSError:
        return False
    if not line.startswith(b"#!"):
        return False
    text = line[2:].strip().decode("utf-8", errors="replace")
    if not text:
        return False
    token = text.split(None, 1)[0]
    if token == "env" or token.endswith("/env"):
        return False
    try:
        return Path(token).resolve() == Path(executable).resolve()
    except OSError:
        return False


def _asc_on_path(executable: str) -> Optional[Path]:
    for name in ("asc", "asc.exe"):
        located = shutil.which(name)
        if not located:
            continue
        candidate = Path(located)
        if not candidate.is_file():
            continue
        if candidate.name == "asc":
            if _shebang_matches(candidate, executable):
                return candidate.resolve()
            continue
        if candidate.name.lower() == "asc.exe" and _exe_belongs_to_interpreter(candidate, executable):
            return candidate.resolve()
    return None


def resolve_asc_executable(argv0: Optional[str] = None) -> Path:
    raw = sys.argv[0] if argv0 is None else argv0
    direct = _asc_file(Path(raw))
    if direct is not None:
        return direct
    # Keep the interpreter path's own directory. Resolving sys.executable
    # follows a venv/conda symlink into the real prefix and misses bin/asc.
    sibling = _asc_file(Path(sys.executable).parent / "asc")
    if sibling is not None:
        return sibling
    windows_sibling = _asc_exe_for_interpreter(sys.executable)
    if windows_sibling is not None:
        return windows_sibling
    located = _asc_on_path(sys.executable)
    if located is not None:
        return located
    raise ScheduleError("not_executable")


def quote_posix_single(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def render_cron_line(asc_path: Path) -> str:
    return f"* * * * * {quote_posix_single(str(asc_path))} schedule tick # asc-schedule"


def render_launch_agent_plist(asc_path: Path, log_path: Path) -> str:
    payload = {
        "Label": _AGENT_LABEL,
        "ProgramArguments": [str(asc_path), "schedule", "tick"],
        "StartInterval": 60,
        "RunAtLoad": False,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }
    return plistlib.dumps(payload).decode("utf-8")


def bootout_command(uid: int, plist: Path) -> list:
    return ["launchctl", "bootout", f"gui/{uid}", str(plist)]


def bootout_service_command(uid: int, label: str = _AGENT_LABEL) -> list:
    return ["launchctl", "bootout", f"gui/{uid}/{label}"]


def bootstrap_command(uid: int, plist: Path) -> list:
    return ["launchctl", "bootstrap", f"gui/{uid}", str(plist)]


def bootout_not_loaded(text: str, returncode: Optional[int] = None) -> bool:
    if returncode in _BOOTOUT_ABSENT_CODES:
        return True
    lowered = text.lower()
    return any(token.lower() in lowered for token in _BOOTOUT_ABSENT)


def bootstrap_already_loaded(text: str, returncode: Optional[int] = None) -> bool:
    if returncode in _BOOTSTRAP_ALREADY_CODES:
        return True
    lowered = text.lower()
    markers = (
        "already bootstrapped",
        "already loaded",
        "file exists",
        "operation already in progress",
        "input/output error",
        "i/o error",
    )
    return any(token in lowered for token in markers)


def _clean_launchctl_output(text: str) -> str:
    kept = [line for line in text.splitlines() if _LAUNCHCTL_ROOT_HINT not in line]
    return "\n".join(kept).strip()


def _ensure_user_agent(backend) -> None:
    ensure = getattr(backend, "ensure_user_agent", None)
    if ensure is not None:
        ensure()


def _require_asc_file(asc_path: Path) -> Path:
    found = _asc_file(asc_path)
    if found is None:
        raise ScheduleError("not_executable")
    return found


def _launch_domain(backend) -> str:
    return f"gui/{backend.uid()}"


def _restore_previous_plist(backend, previous) -> None:
    if previous is None:
        backend.remove_plist()
        return
    backend.write_plist(previous)
    try:
        backend.bootstrap(_launch_domain(backend), backend.plist_path())
    except Exception:
        return


def _install_darwin(asc_path: Path, backend) -> None:
    previous = backend.read_plist()
    xml = render_launch_agent_plist(asc_path, backend.log_path())
    domain = _launch_domain(backend)
    plist = backend.plist_path()
    try:
        backend.write_plist(xml.encode("utf-8"))
        backend.bootout(domain, plist)
        backend.bootstrap(domain, plist)
    except Exception as exc:
        try:
            _restore_previous_plist(backend, previous)
        except Exception:
            pass
        raise ScheduleError("install_failed", reason=str(exc)) from exc


def _cron_lines_without_marker(text: str) -> list:
    return [line for line in text.splitlines() if not line.rstrip().endswith(_CRON_MARKER)]


def _install_cron(asc_path: Path, backend) -> None:
    original = backend.read_crontab()
    kept = _cron_lines_without_marker(original)
    updated = "\n".join([*kept, render_cron_line(asc_path)]) + "\n"
    try:
        backend.write_crontab(updated)
    except Exception as exc:
        try:
            backend.write_crontab(original)
        except Exception:
            pass
        raise ScheduleError("install_failed", reason=str(exc)) from exc


_WINDOWS_TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_WINDOWS_START_BOUNDARY = "2020-01-01T00:00:00"
_SCHTASKS_PERMISSION_MARKERS = (
    "access is denied",
    "access denied",
    "password",
    "logon failure",
    "privilege",
    "elevation",
)


def windows_task_user_id(environ=None) -> str:
    env = os.environ if environ is None else environ
    username = str(env.get("USERNAME") or "").split("\x00", 1)[0].strip()
    if "\\" in username:
        return username
    domain = str(env.get("USERDOMAIN") or "").split("\x00", 1)[0].strip()
    if domain and username:
        return domain + "\\" + username
    if username:
        return ".\\" + username
    return ""


def render_windows_task_xml(asc_path: Path, user_id: str) -> str:
    command = escape(str(asc_path))
    user = escape(user_id)
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.2" xmlns="{_WINDOWS_TASK_NS}">\n'
        "  <Triggers>\n"
        "    <TimeTrigger>\n"
        f"      <StartBoundary>{_WINDOWS_START_BOUNDARY}</StartBoundary>\n"
        "      <Repetition>\n"
        "        <Interval>PT1M</Interval>\n"
        "      </Repetition>\n"
        "    </TimeTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        "    <Principal>\n"
        f"      <UserId>{user}</UserId>\n"
        "      <LogonType>InteractiveToken</LogonType>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "  </Settings>\n"
        "  <Actions>\n"
        "    <Exec>\n"
        f"      <Command>{command}</Command>\n"
        "      <Arguments>schedule tick</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def _decode_schtasks_output(data) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if not isinstance(data, (bytes, bytearray)):
        return str(data)
    blob = bytes(data)
    if blob.startswith((b"\xff\xfe", b"\xfe\xff")):
        return blob.decode("utf-16")
    if b"\x00" in blob[:64]:
        for encoding in ("utf-16", "utf-16-le"):
            try:
                return blob.decode(encoding)
            except UnicodeError:
                continue
    return blob.decode("utf-8", errors="replace")


def _command_from_task_xml(text: str) -> str:
    if not isinstance(text, str):
        return ""
    payload = text.lstrip("\ufeff").strip()
    if not payload or "<" not in payload:
        return ""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ""
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1] != "Command":
            continue
        if elem.text and elem.text.strip():
            return elem.text.strip()
    return ""


def _schtasks_permission_or_password(text: str) -> bool:
    if not text:
        return False
    if "拒绝访问" in text or "密码" in text:
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _SCHTASKS_PERMISSION_MARKERS)


def schtasks_task_missing(returncode: int, stdout: str, stderr: str) -> bool:
    """True when query/delete output shows the task is absent.

    A non-zero exit is not enough. The task is absent when stdout has no
    Command element and stderr contains ERROR without a permission or
    password failure. Any other failure stays ambiguous.
    """
    if returncode == 0:
        return False
    if _command_from_task_xml(stdout):
        return False
    if "ERROR" not in (stderr or "").upper():
        return False
    if _schtasks_permission_or_password(stderr):
        return False
    return True


def _run_schtasks(command: list):
    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )


def _install_windows(asc_path: Path, backend) -> None:
    user_id = windows_task_user_id()
    if not user_id:
        raise ScheduleError("install_failed", reason="USERNAME is not set")
    xml = render_windows_task_xml(asc_path, user_id)
    try:
        backend.write_task_xml(xml)
    except ScheduleError:
        raise
    except Exception as exc:
        raise ScheduleError("install_failed", reason=str(exc)) from exc


def _require_schedule_os(backend) -> None:
    from asc.platform import cli_allows

    system = backend.system() if hasattr(backend, "system") else None
    if not cli_allows("schedule", system):
        raise ScheduleError("os_unsupported")


def install_heartbeat(*, asc_path: Path, backend) -> None:
    _require_schedule_os(backend)
    resolved = _require_asc_file(asc_path)
    if backend.system() == "windows":
        _install_windows(resolved, backend)
        return
    if backend.system() == "darwin":
        _ensure_user_agent(backend)
        _install_darwin(resolved, backend)
        return
    _install_cron(resolved, backend)


def uninstall_heartbeat(*, backend) -> bool:
    _require_schedule_os(backend)
    try:
        if backend.system() == "windows":
            xml = backend.read_task_xml()
            if xml is None:
                return False
            backend.delete_task()
            return True
        if backend.system() == "darwin":
            _ensure_user_agent(backend)
            if backend.read_plist() is None:
                return False
            backend.bootout(_launch_domain(backend), backend.plist_path())
            backend.remove_plist()
            return True
        original = backend.read_crontab()
        if not any(line.rstrip().endswith(_CRON_MARKER) for line in original.splitlines()):
            return False
        kept = _cron_lines_without_marker(original)
        text = "\n".join(kept)
        if original.endswith("\n"):
            text += "\n"
        backend.write_crontab(text)
        return True
    except ScheduleError:
        raise
    except Exception as exc:
        raise ScheduleError("uninstall_failed", reason=str(exc)) from exc


def _unquote_posix_single(text: str) -> str:
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("'\\''", "'")
    return text


def _asc_path_from_cron_line(line: str) -> str:
    text = line.rstrip()
    if not text.startswith(_CRON_PREFIX) or not text.endswith(_CRON_SUFFIX):
        return ""
    quoted = text[len(_CRON_PREFIX) : -len(_CRON_SUFFIX)]
    return _unquote_posix_single(quoted)


def _plist_program(data: bytes) -> str:
    try:
        parsed = plistlib.loads(data)
        arguments = parsed.get("ProgramArguments") or []
        if arguments:
            return str(arguments[0])
    except Exception:
        return ""
    return ""


def heartbeat_status(*, backend) -> dict:
    from asc.platform import cli_allows

    system = backend.system() if hasattr(backend, "system") else None
    if not cli_allows("schedule", system):
        return {"installed": False, "path": ""}
    if backend.system() == "windows":
        try:
            xml = backend.read_task_xml()
        except ScheduleError:
            raise
        except Exception as exc:
            raise ScheduleError("install_failed", reason=str(exc)) from exc
        if xml is None:
            return {"installed": False, "path": ""}
        return {"installed": True, "path": _command_from_task_xml(xml)}
    if backend.system() == "darwin":
        data = backend.read_plist()
        if data is None:
            return {"installed": False, "path": ""}
        return {"installed": True, "path": _plist_program(data)}
    text = backend.read_crontab()
    for line in text.splitlines():
        if line.rstrip().endswith(_CRON_MARKER):
            return {"installed": True, "path": _asc_path_from_cron_line(line)}
    return {"installed": False, "path": ""}


class SystemHeartbeatBackend:
    def system(self) -> str:
        return platform.system().lower()

    def uid(self) -> int:
        return os.getuid()

    def ensure_user_agent(self) -> None:
        geteuid = getattr(os, "geteuid", None)
        if geteuid is not None and geteuid() == 0:
            raise ScheduleError("user_agent")

    def plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / "com.asc.schedule.plist"

    def log_path(self) -> Path:
        return Path.home() / ".config" / "asc" / "schedule-tick.log"

    def read_plist(self):
        path = self.plist_path()
        if not path.is_file():
            return None
        return path.read_bytes()

    def write_plist(self, data: bytes) -> None:
        self.log_path().parent.mkdir(parents=True, exist_ok=True)
        path = self.plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def remove_plist(self) -> None:
        path = self.plist_path()
        if path.exists():
            path.unlink()

    def bootout(self, domain, plist) -> None:
        uid = int(str(domain).rsplit("/", 1)[-1])
        self._run_bootout(bootout_command(uid, Path(plist)))

    def _run_bootout(self, command: list) -> None:
        completed = subprocess.run(command, capture_output=True, text=True)
        output = f"{completed.stdout or ''}{completed.stderr or ''}"
        if completed.returncode != 0 and not bootout_not_loaded(output, completed.returncode):
            message = _clean_launchctl_output(output) or f"bootout exited {completed.returncode}"
            raise RuntimeError(message)

    def bootstrap(self, domain, plist) -> None:
        self._bootstrap(domain, plist, allow_reload=True)

    def _bootstrap(self, domain, plist, allow_reload: bool) -> None:
        uid = int(str(domain).rsplit("/", 1)[-1])
        completed = subprocess.run(
            bootstrap_command(uid, Path(plist)),
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return
        output = f"{completed.stdout or ''}{completed.stderr or ''}"
        # One reload when launchctl reports the service is already bootstrapped.
        # A second failure propagates and the installer rolls the plist back.
        if allow_reload and bootstrap_already_loaded(output, completed.returncode):
            self._run_bootout(bootout_service_command(uid))
            self._bootstrap(domain, plist, allow_reload=False)
            return
        message = _clean_launchctl_output(output) or f"bootstrap exited {completed.returncode}"
        raise RuntimeError(message)

    def read_crontab(self) -> str:
        completed = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        stderr = completed.stderr or ""
        if "no crontab" in stderr.lower():
            return ""
        if completed.returncode != 0:
            raise RuntimeError(stderr.strip() or "crontab -l failed")
        return completed.stdout or ""

    def write_crontab(self, text: str) -> None:
        completed = subprocess.run(
            ["crontab", "-"],
            input=text,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "crontab failed").strip()
            raise RuntimeError(message)

    def read_task_xml(self) -> Optional[str]:
        completed = _run_schtasks(["schtasks", "/Query", "/TN", _AGENT_LABEL, "/XML"])
        stdout = _decode_schtasks_output(completed.stdout)
        stderr = _decode_schtasks_output(completed.stderr)
        if completed.returncode == 0 or _command_from_task_xml(stdout):
            return stdout
        if schtasks_task_missing(completed.returncode, stdout, stderr):
            return None
        message = (stderr or stdout or f"schtasks exited {completed.returncode}").strip()
        raise RuntimeError(message)

    def write_task_xml(self, xml: str) -> None:
        fd, raw_name = tempfile.mkstemp(prefix="asc-schedule-", suffix=".xml")
        os.close(fd)
        path = Path(raw_name)
        try:
            path.write_bytes(str(xml).encode("utf-16"))
            completed = _run_schtasks(
                ["schtasks", "/Create", "/TN", _AGENT_LABEL, "/XML", str(path), "/F"]
            )
            if completed.returncode != 0:
                stdout = _decode_schtasks_output(completed.stdout)
                stderr = _decode_schtasks_output(completed.stderr)
                message = (stderr or stdout or f"schtasks exited {completed.returncode}").strip()
                raise RuntimeError(message)
        finally:
            try:
                path.unlink()
            except OSError:
                pass

    def delete_task(self) -> None:
        completed = _run_schtasks(["schtasks", "/Delete", "/TN", _AGENT_LABEL, "/F"])
        if completed.returncode == 0:
            return
        stdout = _decode_schtasks_output(completed.stdout)
        stderr = _decode_schtasks_output(completed.stderr)
        if schtasks_task_missing(completed.returncode, stdout, stderr):
            return
        message = (stderr or stdout or f"schtasks exited {completed.returncode}").strip()
        raise RuntimeError(message)


def default_profile_lookup(name: str):
    from asc.config import Config

    config = Config.__new__(Config)
    config._global_dir = Path.home() / ".config" / "asc"
    config._data = {}
    config.app_name = None
    return config.get_app_profile(name)


def _valid_interval_hours(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _normalize_weekdays(value):
    if not isinstance(value, list) or not value:
        raise ScheduleError("weekdays")
    days = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1 or item > 7:
            raise ScheduleError("weekdays")
        days.append(item)
    if len(days) != len(set(days)):
        raise ScheduleError("weekdays")
    return sorted(days)


def _validate_kind_fields(kind: str, interval_hours, weekdays):
    if kind == "daily":
        if interval_hours is not None or weekdays is not None:
            raise ScheduleError("kind_fields")
        return None, None
    if kind == "interval":
        if weekdays is not None or not _valid_interval_hours(interval_hours):
            raise ScheduleError("kind_fields")
        return interval_hours, None
    if kind == "weekly":
        if interval_hours is not None or weekdays is None:
            raise ScheduleError("kind_fields")
        return None, _normalize_weekdays(weekdays)
    raise ScheduleError("kind_fields")


def _require_profile(name: str, profile_lookup):
    if profile_lookup(name) is None:
        raise ScheduleError("profile", name=name)


def _find_task(tasks: list, task_id: str) -> ScheduleTask:
    for task in tasks:
        if task.id == task_id:
            return task
    raise ScheduleNotFound(task_id)


def _weekday_key(weekdays):
    if weekdays is None:
        return None
    return tuple(weekdays)


def add_task(
    *,
    profile: str,
    kind: str,
    time: str,
    interval_hours: Optional[int] = None,
    weekdays: Optional[list] = None,
    enabled: bool = True,
    watch: str = WATCH_APP_STORE,
    schedule_path: Path,
    now: datetime,
    profile_lookup,
    backend,
    asc_path: Path,
    environ=None,
    localtime: Optional[Path] = None,
    timezone: Optional[str] = None,
) -> tuple:
    parse_hhmm(time)
    interval_hours, weekdays = _validate_kind_fields(kind, interval_hours, weekdays)
    watch = require_watch(watch)
    if not isinstance(enabled, bool):
        raise ScheduleError("enabled")
    _require_profile(profile, profile_lookup)
    if timezone is None:
        timezone_name = capture_timezone(environ=environ, localtime=localtime)
    else:
        timezone_name = require_timezone_name(timezone)
    installed_now = False
    with schedule_lock(schedule_path, blocking=True):
        _require_profile(profile, profile_lookup)
        if not heartbeat_status(backend=backend)["installed"]:
            install_heartbeat(asc_path=asc_path, backend=backend)
            installed_now = True
        tasks = load_tasks(schedule_path)
        task = ScheduleTask(
            id=new_task_id({item.id for item in tasks}),
            profile=profile,
            enabled=enabled,
            kind=kind,
            time=time,
            timezone=timezone_name,
            next_run_at="1970-01-01T00:00:00+00:00",
            last_run_at="",
            last_error="",
            last_result="",
            interval_hours=interval_hours,
            weekdays=weekdays,
            watch=watch,
        )
        task.next_run_at = format_timestamp(next_slot(task, now))
        tasks.append(task)
        save_tasks(schedule_path, tasks)
    return task, installed_now


def list_tasks(*, schedule_path: Path) -> list:
    if not schedule_path.exists() and not schedule_path.parent.exists():
        return []
    with schedule_lock(schedule_path, blocking=True):
        return load_tasks(schedule_path)


def set_enabled(task_id: str, enabled: bool, *, schedule_path: Path) -> ScheduleTask:
    if not isinstance(enabled, bool):
        raise ScheduleError("enabled")
    with schedule_lock(schedule_path, blocking=True):
        tasks = load_tasks(schedule_path)
        task = _find_task(tasks, task_id)
        if task.enabled == enabled:
            return task
        task.enabled = enabled
        save_tasks(schedule_path, tasks)
        return task


def remove_task(task_id: str, *, schedule_path: Path) -> None:
    with schedule_lock(schedule_path, blocking=True):
        tasks = load_tasks(schedule_path)
        _find_task(tasks, task_id)
        save_tasks(schedule_path, [item for item in tasks if item.id != task_id])


def update_task(
    task_id: str,
    *,
    profile: str,
    kind: str,
    time: str,
    enabled: bool,
    interval_hours: Optional[int],
    weekdays: Optional[list],
    schedule_path: Path,
    now: datetime,
    profile_lookup,
    watch: Optional[str] = None,
) -> ScheduleTask:
    parse_hhmm(time)
    interval_hours, weekdays = _validate_kind_fields(kind, interval_hours, weekdays)
    if watch is not None:
        watch = require_watch(watch)
    if not isinstance(enabled, bool):
        raise ScheduleError("enabled")
    _require_profile(profile, profile_lookup)
    with schedule_lock(schedule_path, blocking=True):
        _require_profile(profile, profile_lookup)
        tasks = load_tasks(schedule_path)
        task = _find_task(tasks, task_id)
        changed = (
            task.kind != kind
            or task.time != time
            or task.interval_hours != interval_hours
            or _weekday_key(task.weekdays) != _weekday_key(weekdays)
        )
        task.profile = profile
        task.kind = kind
        task.time = time
        task.enabled = enabled
        task.interval_hours = interval_hours
        task.weekdays = weekdays
        if watch is not None:
            task.watch = watch
        if changed:
            task.next_run_at = format_timestamp(next_slot(task, now))
        save_tasks(schedule_path, tasks)
        return task


def _clock_candidates(task: ScheduleTask, day: date, hour: int, minute: int, anchor: int):
    if task.kind == "daily":
        return [(hour, minute)]
    if task.kind == "weekly":
        if day.isoweekday() not in set(task.weekdays or []):
            return []
        return [(hour, minute)]
    if task.kind == "interval":
        period = int(task.interval_hours) * 60
        found = []
        for minute_of_day in range(24 * 60):
            if (minute_of_day - anchor) % period == 0:
                found.append(divmod(minute_of_day, 60))
        return found
    return []


IN_REVIEW_LABELS = {
    "WAITING_FOR_REVIEW": "等待审核",
    "IN_REVIEW": "审核中",
    "REJECTED": "被拒",
    "METADATA_REJECTED": "被拒",
    "PENDING_DEVELOPER_RELEASE": "待开发者发布",
    "PENDING_APPLE_RELEASE": "待 Apple 发布",
    "APPROVED": "已通过",
}

# In-progress review: notify every tick, and clear last_notified_result.
REVIEW_IN_PROGRESS_STATES = frozenset(
    {
        "WAITING_FOR_REVIEW",
        "IN_REVIEW",
        "WAITING_FOR_BETA_REVIEW",
        "IN_BETA_REVIEW",
    }
)
REVIEW_APPROVED_STATES = frozenset(
    {
        "APPROVED",
        "PENDING_DEVELOPER_RELEASE",
        "PENDING_APPLE_RELEASE",
        "READY_FOR_SALE",
        "BETA_APPROVED",
        "READY_FOR_BETA_TESTING",
        "IN_BETA_TESTING",
    }
)
REVIEW_REJECTED_STATES = frozenset(
    {
        "REJECTED",
        "METADATA_REJECTED",
        "BETA_REJECTED",
    }
)
REVIEW_IN_PROGRESS_LABELS = frozenset(
    {
        "等待审核",
        "审核中",
        "等待 Beta 审核",
        "Beta 审核中",
    }
)
REVIEW_APPROVED_LABELS = frozenset(
    {
        "待开发者发布",
        "待 Apple 发布",
        "已通过",
        "Beta 已通过",
    }
)
REVIEW_REJECTED_LABELS = frozenset(
    {
        "被拒",
        "Beta 被拒",
    }
)
REVIEW_PHASE_IN_PROGRESS = "in_progress"
REVIEW_PHASE_APPROVED = "approved"
REVIEW_PHASE_REJECTED = "rejected"


TF_EMPTY_NOTES = {
    "no_external_groups": "没有 TestFlight 外部测试组",
    "no_builds": "外部测试组没有构建",
}


class ReviewSnapshot:
    def __init__(
        self,
        in_review: list,
        on_sale: list,
        watch: str = WATCH_APP_STORE,
        note: str = "",
    ) -> None:
        self.in_review = in_review
        self.on_sale = on_sale
        self.watch = watch if watch in VALID_WATCH else WATCH_APP_STORE
        self.note = note or ""


def _version_state(attributes: dict):
    if "appStoreState" in attributes:
        return attributes.get("appStoreState")
    if "appVersionState" in attributes:
        return attributes.get("appVersionState")
    return None


def _version_name(attributes: dict) -> str:
    raw = attributes.get("versionString")
    text = raw.strip() if isinstance(raw, str) else ""
    return text or "未知版本"


def classify_versions(versions: list) -> ReviewSnapshot:
    seen = set()
    in_review = []
    on_sale = []
    for version in versions:
        version_id = version.get("id")
        if version_id:
            if version_id in seen:
                continue
            seen.add(version_id)
        attributes = version.get("attributes") or {}
        if not isinstance(attributes, dict):
            continue
        state = _version_state(attributes)
        if not isinstance(state, str) or not state:
            continue
        name = _version_name(attributes)
        if state in IN_REVIEW_LABELS:
            in_review.append((name, IN_REVIEW_LABELS[state]))
        elif state == "READY_FOR_SALE":
            on_sale.append(name)
    if in_review:
        return ReviewSnapshot(in_review, [])
    return ReviewSnapshot([], on_sale)


def format_last_result(snapshot: ReviewSnapshot) -> str:
    if snapshot.watch == WATCH_TESTFLIGHT:
        if snapshot.in_review:
            return "；".join(f"TF {name} {label}" for name, label in snapshot.in_review)
        if snapshot.on_sale:
            return "当前无 TF 外部组在审构建；可测试 " + "、".join(snapshot.on_sale)
        if snapshot.note in TF_EMPTY_NOTES:
            return TF_EMPTY_NOTES[snapshot.note]
        return "当前无 TF 外部组在审构建；暂无可测试构建"
    if snapshot.in_review:
        return "；".join(f"{name} {label}" for name, label in snapshot.in_review)
    if snapshot.on_sale:
        return "当前无在审版本；已上架 " + "、".join(snapshot.on_sale)
    return "当前无在审版本；暂无已上架版本"


def review_phase(token: str) -> str:
    if token in REVIEW_IN_PROGRESS_STATES or token in REVIEW_IN_PROGRESS_LABELS:
        return REVIEW_PHASE_IN_PROGRESS
    if token in REVIEW_APPROVED_STATES or token in REVIEW_APPROVED_LABELS:
        return REVIEW_PHASE_APPROVED
    if token in REVIEW_REJECTED_STATES or token in REVIEW_REJECTED_LABELS:
        return REVIEW_PHASE_REJECTED
    return ""


def snapshot_has_in_progress(snapshot: Optional[ReviewSnapshot]) -> bool:
    if snapshot is None:
        return False
    return any(review_phase(label) == REVIEW_PHASE_IN_PROGRESS for _name, label in snapshot.in_review)


def snapshot_lacks_review_status(snapshot: Optional[ReviewSnapshot]) -> bool:
    """True when a query succeeded but nothing reportable was found.

    Empty App Store / TestFlight snapshots, TF empty notes, and
    non-reportable rows such as 未送审 count as missing status. Query
    failures (``snapshot is None``) do not.
    """
    if snapshot is None:
        return False
    if snapshot_has_in_progress(snapshot):
        return False
    if any(name for name in snapshot.on_sale if name):
        return False
    reportable = {REVIEW_PHASE_APPROVED, REVIEW_PHASE_REJECTED}
    return not any(review_phase(label) in reportable for _name, label in snapshot.in_review)


def review_result_notify_key(snapshot: ReviewSnapshot, profile: str) -> Optional[str]:
    pairs = []
    for name, label in snapshot.in_review:
        phase = review_phase(label)
        if phase == REVIEW_PHASE_IN_PROGRESS:
            return None
        if phase in {REVIEW_PHASE_APPROVED, REVIEW_PHASE_REJECTED}:
            pairs.append((str(name), phase))
            continue
        return None
    for name in snapshot.on_sale:
        if name:
            pairs.append((str(name), REVIEW_PHASE_APPROVED))
    if not pairs:
        return None
    watch = snapshot.watch if snapshot.watch in VALID_WATCH else WATCH_APP_STORE
    body = ";".join(f"{name}:{phase}" for name, phase in sorted(pairs))
    return f"{watch}|{profile}|{body}"


def review_notify_decision(task: ScheduleTask, outcome: "QueryOutcome") -> tuple:
    previous = getattr(task, "last_notified_result", "") or ""
    if outcome.query_error or outcome.snapshot is None:
        return True, previous
    snapshot = outcome.snapshot
    if snapshot_has_in_progress(snapshot):
        return True, ""
    key = review_result_notify_key(snapshot, task.profile)
    if key is None:
        return True, previous
    if previous == key:
        return False, key
    return True, key


def format_checked_at(now: datetime, timezone_name: str) -> str:
    local = now.astimezone(ZoneInfo(timezone_name)).replace(microsecond=0)
    return f"{local.strftime('%Y-%m-%d %H:%M')}（{timezone_name}）"


def watch_label(watch: str) -> str:
    from asc.i18n import LANG, SCHEDULE_TEXT, t

    if LANG == "en":
        key = (
            "notify_watch_testflight"
            if watch == WATCH_TESTFLIGHT
            else "notify_watch_app_store"
        )
        return t(SCHEDULE_TEXT[key])
    return WATCH_LABELS.get(watch, WATCH_LABELS[WATCH_APP_STORE])


def markdown_bold(text: str) -> str:
    value = str(text)
    if value.startswith("**") and value.endswith("**") and len(value) >= 4:
        return value
    return f"**{value}**"


def _notify_line(key: str, **params: object) -> str:
    from asc.i18n import SCHEDULE_TEXT, t

    return t(SCHEDULE_TEXT[key]).format(**params)


def build_success_message(profile: str, checked_at: str, snapshot: ReviewSnapshot) -> str:
    return "\n".join(
        [
            markdown_bold(format_last_result(snapshot)),
            _notify_line("notify_app", profile=profile),
            _notify_line("notify_watch", watch=watch_label(snapshot.watch)),
            _notify_line("notify_checked_at", checked_at=checked_at),
        ]
    )


def build_failure_message(
    profile: str,
    checked_at: str,
    error: str,
    watch: str = WATCH_APP_STORE,
) -> str:
    return "\n".join(
        [
            markdown_bold(_notify_line("notify_fail", error=error)),
            _notify_line("notify_app", profile=profile),
            _notify_line("notify_watch", watch=watch_label(watch)),
            _notify_line("notify_checked_at", checked_at=checked_at),
        ]
    )


def build_test_message(
    profile: str,
    checked_at: str,
    watch: str = WATCH_APP_STORE,
) -> str:
    return "\n".join(
        [
            markdown_bold(_notify_line("notify_test")),
            _notify_line("notify_app", profile=profile),
            _notify_line("notify_watch", watch=watch_label(watch)),
            _notify_line("notify_checked_at", checked_at=checked_at),
        ]
    )


def _missing_notification_channel(outcome: "SendOutcome") -> bool:
    return not outcome.config_invalid and not outcome.failures and not outcome.attempted


def clamp_error(text: str) -> str:
    from asc.web.notifications import _sanitize_message_text

    flattened = str(text).replace("\r", " ").replace("\n", " ")
    return _sanitize_message_text(flattened)[:200]


class QueryOutcome:
    def __init__(self, last_result: str, query_error: str, snapshot: Optional[ReviewSnapshot]) -> None:
        self.last_result = last_result
        self.query_error = query_error
        self.snapshot = snapshot


class SendOutcome:
    def __init__(self, config_invalid: bool, failures: list, attempted: bool) -> None:
        self.config_invalid = config_invalid
        self.failures = failures
        self.attempted = attempted


_PROVIDER_ORDER = ("feishu", "wecom", "dingtalk")


def _credential_text(creds: dict, key: str) -> str:
    value = creds.get(key, "")
    if not isinstance(value, str):
        return ""
    return value.strip()


def _key_file_opens(path: str) -> bool:
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def _credentials_ready(creds: dict) -> bool:
    fields = [_credential_text(creds, key) for key in ("issuer_id", "key_id", "key_file", "app_id")]
    if not all(fields):
        return False
    return _key_file_opens(fields[2])


def _default_api_factory(issuer_id: str, key_id: str, key_file: str):
    from asc.api import AppStoreConnectAPI

    return AppStoreConnectAPI(issuer_id, key_id, key_file)


def _default_guard(profile: str, creds: dict) -> None:
    from asc.guard import Guard

    guard = Guard()
    if not guard.is_enabled():
        return
    guard.check_and_enforce(
        _credential_text(creds, "app_id"),
        app_name=profile,
        key_id=_credential_text(creds, "key_id"),
        issuer_id=_credential_text(creds, "issuer_id"),
        interactive=False,
    )


def _open_query_api(
    profile: str,
    *,
    profile_lookup=None,
    api_factory=None,
    guard=None,
):
    from asc.guard import GuardError, GuardViolationError

    lookup = default_profile_lookup if profile_lookup is None else profile_lookup
    creds = lookup(profile)
    if creds is None:
        return QueryOutcome("检查失败", "profile 不存在", None), None, ""
    if not isinstance(creds, dict) or not _credentials_ready(creds):
        return QueryOutcome("检查失败", "凭证不完整", None), None, ""
    try:
        if guard is None:
            _default_guard(profile, creds)
        else:
            guard(profile, creds)
    except (GuardViolationError, GuardError) as exc:
        return QueryOutcome("检查失败", clamp_error(str(exc)), None), None, ""
    factory = _default_api_factory if api_factory is None else api_factory
    issuer_id = _credential_text(creds, "issuer_id")
    key_id = _credential_text(creds, "key_id")
    key_file = _credential_text(creds, "key_file")
    app_id = _credential_text(creds, "app_id")
    try:
        api = factory(issuer_id, key_id, key_file)
    except Exception as exc:
        return QueryOutcome("检查失败", clamp_error(str(exc)), None), None, ""
    return None, api, app_id


def query_testflight(
    profile: str,
    *,
    profile_lookup=None,
    api_factory=None,
    guard=None,
) -> QueryOutcome:
    from asc.testflight import classify_testflight_builds, fetch_testflight_builds

    failed, api, app_id = _open_query_api(
        profile,
        profile_lookup=profile_lookup,
        api_factory=api_factory,
        guard=guard,
    )
    if failed is not None:
        return failed
    try:
        result = fetch_testflight_builds(api, app_id)
        in_review, ready = classify_testflight_builds(result.builds)
        snapshot = ReviewSnapshot(
            in_review,
            ready,
            watch=WATCH_TESTFLIGHT,
            note=result.empty_reason,
        )
    except Exception as exc:
        return QueryOutcome("检查失败", clamp_error(str(exc)), None)
    return QueryOutcome(format_last_result(snapshot), "", snapshot)


def query_review(
    profile: str,
    *,
    profile_lookup=None,
    api_factory=None,
    guard=None,
    watch: str = WATCH_APP_STORE,
) -> QueryOutcome:
    if watch == WATCH_TESTFLIGHT:
        return query_testflight(
            profile,
            profile_lookup=profile_lookup,
            api_factory=api_factory,
            guard=guard,
        )
    failed, api, app_id = _open_query_api(
        profile,
        profile_lookup=profile_lookup,
        api_factory=api_factory,
        guard=guard,
    )
    if failed is not None:
        return failed
    try:
        versions = api._get_paginated_data(
            f"/v1/apps/{app_id}/appStoreVersions",
            **{"filter[platform]": "IOS"},
        )
        snapshot = classify_versions(versions)
    except Exception as exc:
        return QueryOutcome("检查失败", clamp_error(str(exc)), None)
    return QueryOutcome(format_last_result(snapshot), "", snapshot)


def _default_sender(provider: str, config: dict, text: str):
    from asc.web.webhook_clients import send_provider

    return send_provider(provider, config, text)


def send_channels(text: str, *, sender=None) -> SendOutcome:
    from asc.web.notifications import (
        WebhookConfigError,
        _load_webhook_config_for_notification,
    )

    try:
        config = _load_webhook_config_for_notification()
    except WebhookConfigError:
        return SendOutcome(True, [], False)
    if not config.get("enabled"):
        return SendOutcome(False, [], False)
    send = _default_sender if sender is None else sender
    providers = config.get("providers") or {}
    failures = []
    attempted = False
    for provider in _PROVIDER_ORDER:
        channel = providers.get(provider) or {}
        if not channel.get("enabled"):
            continue
        url = str(channel.get("url") or "").strip()
        if not url:
            continue
        attempted = True
        try:
            result = send(provider, channel, text)
        except Exception as exc:
            failures.append(f"{provider} {exc}")
            continue
        if not isinstance(result, dict) or not result.get("ok"):
            error = result.get("error") if isinstance(result, dict) else "发送失败"
            failures.append(f"{provider} {error}")
    return SendOutcome(False, failures, attempted)


def combine_last_error(query_error: str, outcome: SendOutcome) -> str:
    parts = []
    if query_error:
        parts.append(query_error)
    if outcome.config_invalid:
        parts.append("通知配置无效")
    elif outcome.failures:
        parts.append("通知发送失败：" + "；".join(outcome.failures))
    return "；".join(parts)


def user_message(code: str, **params: object) -> str:
    from asc.i18n import SCHEDULE_TEXT, t

    text = t(SCHEDULE_TEXT[code])
    return text.format(**params) if params else text


def _default_send(text: str) -> SendOutcome:
    return send_channels(text)


def _stamp_last_run(task: ScheduleTask, now: datetime) -> str:
    local = now.astimezone(ZoneInfo(task.timezone)).replace(microsecond=0)
    return format_timestamp(local)


def _task_watch(task: ScheduleTask) -> str:
    watch = getattr(task, "watch", None)
    return watch if watch in VALID_WATCH else WATCH_APP_STORE


def _invoke_query(query, task: ScheduleTask):
    watch = _task_watch(task)
    try:
        return query(task.profile, watch=watch)
    except TypeError:
        return query(task.profile)


def execute_task(
    task: ScheduleTask,
    tasks: list,
    schedule_path: Path,
    now: datetime,
    *,
    advance_next: bool,
    query,
    send,
    force_test_on_empty: bool = False,
) -> str:
    try:
        outcome = _invoke_query(query, task)
    except Exception as exc:
        outcome = QueryOutcome("检查失败", clamp_error(str(exc)), None)
    if not isinstance(outcome, QueryOutcome):
        outcome = QueryOutcome("检查失败", clamp_error(str(outcome)), None)
    send_test = bool(
        force_test_on_empty
        and not outcome.query_error
        and snapshot_lacks_review_status(outcome.snapshot)
    )
    task.last_run_at = _stamp_last_run(task, now)
    task.last_result = _notify_line("notify_test") if send_test else outcome.last_result
    task.last_error = outcome.query_error
    if advance_next:
        task.next_run_at = format_timestamp(next_slot(task, now))
    if send_test:
        should_send = True
        notified_after = task.last_notified_result or ""
    else:
        should_send, notified_after = review_notify_decision(task, outcome)
    if snapshot_has_in_progress(outcome.snapshot):
        task.last_notified_result = ""
    save_tasks(schedule_path, tasks)
    if not should_send:
        return "ok"
    checked = format_checked_at(now, task.timezone)
    if outcome.query_error or outcome.snapshot is None:
        text = build_failure_message(
            task.profile,
            checked,
            outcome.query_error or "检查失败",
            watch=_task_watch(task),
        )
    elif send_test:
        text = build_test_message(task.profile, checked, watch=_task_watch(task))
    else:
        text = build_success_message(task.profile, checked, outcome.snapshot)
    send_outcome = send(text)
    if send_test and _missing_notification_channel(send_outcome):
        final_error = user_message("notify_no_channel")
    else:
        final_error = combine_last_error(outcome.query_error, send_outcome)
    dirty = False
    if final_error != task.last_error:
        task.last_error = final_error
        dirty = True
    if (
        not send_test
        and not final_error
        and notified_after != (task.last_notified_result or "")
    ):
        task.last_notified_result = notified_after
        dirty = True
    if dirty:
        save_tasks(schedule_path, tasks)
    if task.last_error:
        return "error"
    return "ok"


def _tick_locked(schedule_path: Path, now, query, send) -> int:
    if now is None:
        now = datetime.now().astimezone()
    try:
        tasks = load_tasks(schedule_path)
    except ScheduleCorruptError:
        print(user_message("corrupt"), file=sys.stderr)
        return 1
    for task in tasks:
        if not task.enabled:
            continue
        planned = parse_timestamp(task.next_run_at)
        if planned > now:
            continue
        try:
            if due_action(planned, now) == "skip":
                task.next_run_at = format_timestamp(next_slot(task, now))
                save_tasks(schedule_path, tasks)
                print(f"{task.id} {task.profile} skipped", flush=True)
                continue
            status = execute_task(
                task,
                tasks,
                schedule_path,
                now,
                advance_next=True,
                query=query,
                send=send,
            )
        except Exception as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"{task.id} {task.profile} {status}", flush=True)
    return 0


def tick(*, schedule_path: Path, now=None, query=None, send=None) -> int:
    if not schedule_path.exists() and not schedule_path.parent.exists():
        return 0
    query_fn = query_review if query is None else query
    send_fn = _default_send if send is None else send
    try:
        with schedule_lock(schedule_path, blocking=False):
            return _tick_locked(schedule_path, now, query_fn, send_fn)
    except ScheduleLockBusy:
        print(user_message("lock_busy"), file=sys.stderr)
        return 0
    except ScheduleError as exc:
        if exc.code == "fcntl_unavailable":
            print(user_message("fcntl_unavailable"), file=sys.stderr)
            return 1
        raise


def run_task(
    task_id: str,
    *,
    schedule_path: Path,
    now=None,
    query=None,
    send=None,
) -> ScheduleTask:
    if now is None:
        now = datetime.now().astimezone()
    query_fn = query_review if query is None else query
    send_fn = _default_send if send is None else send
    with schedule_lock(schedule_path, blocking=True, timeout=30):
        tasks = load_tasks(schedule_path)
        task = _find_task(tasks, task_id)
        execute_task(
            task,
            tasks,
            schedule_path,
            now,
            advance_next=False,
            query=query_fn,
            send=send_fn,
            force_test_on_empty=True,
        )
        return task
