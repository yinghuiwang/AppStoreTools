# src/asc/commands/guard_cmd.py
from __future__ import annotations
from typing import Optional

import typer
from asc.guard import Guard
from asc.i18n import t, HELP

guard_app = typer.Typer(help=t(HELP['cmd_guard']), no_args_is_help=True)


def _format_bound_at(value: str) -> str:
    if not value:
        return "未知"
    return value[:19].replace("T", " ")


def _format_app_label(entry: dict) -> str:
    app_name = (entry.get("app_name") or "").strip()
    app_id = str(entry.get("app_id") or "").strip()
    if app_name and app_id:
        return f"{app_name} ({app_id})"
    return app_name or app_id or "未知"


def _echo_binding_detail(
    label: str,
    key: str,
    entry: dict | None,
    *,
    note: str = "",
) -> None:
    """Print one current-environment binding line with status details."""
    typer.echo(f"  {label}: {key}")
    if not entry:
        typer.echo("    状态: ❌ 未绑定")
        return
    typer.echo("    状态: ✅ 已绑定")
    typer.echo(f"    绑定 App: {_format_app_label(entry)}")
    if note:
        typer.echo(f"    备注: {note}")


@guard_app.command("status")
def cmd_guard_status():
    """查看当前绑定状态。"""
    g = Guard()
    data = g.get_status()
    enabled = g.is_enabled()
    status_str = "✅ 已启用" if enabled else "❌ 已禁用"
    typer.echo(f"\n守卫状态: {status_str}\n")

    fp = g._get_machine_fingerprint()
    ip = g._get_public_ip()
    bindings = data.get("bindings", {})
    app_notes = data.get("app_notes", {})
    machine_entry = bindings.get("machine", {}).get(fp)
    ip_entry = None if ip == "unknown" else bindings.get("ip", {}).get(ip)

    machine_note = app_notes.get((machine_entry or {}).get("app_id", ""), "") if machine_entry else ""
    ip_note = app_notes.get((ip_entry or {}).get("app_id", ""), "") if ip_entry else ""

    typer.echo("当前环境:")
    _echo_binding_detail("机器指纹", fp, machine_entry, note=machine_note)
    if ip == "unknown":
        typer.echo("  IP 地址:  unknown")
        typer.echo("    状态: ⚠️  无法获取，跳过 IP 绑定检查")
    else:
        _echo_binding_detail("IP 地址", ip, ip_entry, note=ip_note)
    typer.echo("")

    rows = []
    for entry_key, entry_val in bindings.get("machine", {}).items():
        rows.append(("机器", entry_key, entry_val.get("app_name", ""), _format_bound_at(entry_val.get("bound_at", "")), app_notes.get(entry_val.get("app_id", ""), "")))
    for entry_key, entry_val in bindings.get("ip", {}).items():
        rows.append(("IP", entry_key, entry_val.get("app_name", ""), _format_bound_at(entry_val.get("bound_at", "")), app_notes.get(entry_val.get("app_id", ""), "")))
    for entry_key, entry_val in bindings.get("credential", {}).items():
        rows.append(("凭证", entry_key, entry_val.get("app_name", ""), _format_bound_at(entry_val.get("bound_at", "")), app_notes.get(entry_val.get("app_id", ""), "")))

    if not rows:
        typer.echo("绑定记录: (无)\n")
        return

    typer.echo("绑定记录:")
    typer.echo(f"  {'类型':<8} {'标识':<20} {'绑定 App':<14} {'绑定时间':<19} {'备注'}")
    typer.echo("  " + "-" * 84)
    for btype, bkey, bapp, bat, note in rows:
        typer.echo(f"  {btype:<8} {bkey:<20} {bapp:<14} {bat:<19} {note}")
    typer.echo(f"\n提示: 使用 'asc guard unbind' 解除绑定")


@guard_app.command("enable")
def cmd_guard_enable():
    """启用守卫功能。"""
    g = Guard()
    g.enable()
    typer.echo("✅ 守卫功能已启用")


@guard_app.command("disable")
def cmd_guard_disable():
    """禁用守卫功能。"""
    g = Guard()
    g.disable()
    typer.echo("⚠️  守卫功能已禁用")


@guard_app.command("reset")
def cmd_guard_reset():
    """清除所有绑定记录（保留启用/禁用状态）。"""
    g = Guard()
    data = g.get_status()
    total = sum(len(v) for v in data.get("bindings", {}).values())
    if total == 0:
        typer.echo("绑定记录为空，无需重置")
        return
    confirm = typer.prompt(f"将清除 {total} 条绑定记录，确认? [yes/no]")
    if confirm.strip().lower() != "yes":
        typer.echo("已取消")
        raise typer.Exit(0)
    g._data["bindings"] = {"machine": {}, "ip": {}, "credential": {}}
    g._data["app_notes"] = {}
    g._save()
    typer.echo("✅ 所有绑定记录已清除")


@guard_app.command("unbind")
def cmd_guard_unbind(
    machine: Optional[str] = typer.Option(None, "--machine", help="按机器指纹解绑"),
    ip: Optional[str] = typer.Option(None, "--ip", help="按 IP 地址解绑"),
    credential: Optional[str] = typer.Option(None, "--credential", help="按 API key_id 解绑"),
    current: bool = typer.Option(False, "--current", help="解除当前机器/IP/凭证的绑定"),
):
    """解除指定绑定。"""
    g = Guard()
    removed = 0
    if current:
        fp = g._get_machine_fingerprint()
        pub_ip = g._get_public_ip()
        for btype, bkey in [("machine", fp), ("ip", pub_ip)]:
            if bkey in g._data["bindings"].get(btype, {}):
                g.unbind(btype, bkey)
                typer.echo(f"✅ 已解除 {btype} 绑定: {bkey}")
                removed += 1
    if machine:
        g.unbind("machine", machine)
        typer.echo(f"✅ 已解除机器绑定: {machine}")
        removed += 1
    if ip:
        g.unbind("ip", ip)
        typer.echo(f"✅ 已解除 IP 绑定: {ip}")
        removed += 1
    if credential:
        g.unbind("credential", credential)
        typer.echo(f"✅ 已解除凭证绑定: {credential}")
        removed += 1
    if removed == 0:
        typer.echo("未指定任何解绑目标，请使用 --machine / --ip / --credential / --current", err=True)
        raise typer.Exit(1)


@guard_app.command("note")
def cmd_guard_note(
    app_id: str = typer.Option(..., "--app-id", help="App ID"),
    note: str = typer.Option("", "--note", help="备注内容"),
):
    """添加或更新 App 备注。"""
    g = Guard()
    if not g.set_app_note(app_id, note):
        typer.echo(f"未找到 App 绑定: {app_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"✅ 已更新 App 备注: {app_id} -> {note}")
