# src/asc/commands/guard_cmd.py
from __future__ import annotations

import typer
from asc.guard import Guard

guard_app = typer.Typer(help="管理 App 绑定守卫功能", no_args_is_help=True)


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
    typer.echo("当前环境:")
    typer.echo(f"  机器指纹: {fp[:16]}...")
    typer.echo(f"  IP 地址:  {ip}\n")

    bindings = data.get("bindings", {})
    rows = []
    for entry_key, entry_val in bindings.get("machine", {}).items():
        rows.append(("机器", entry_key[:16] + "...", entry_val.get("app_name", ""), entry_val.get("bound_at", "")[:19].replace("T", " ")))
    for entry_key, entry_val in bindings.get("ip", {}).items():
        rows.append(("IP", entry_key, entry_val.get("app_name", ""), entry_val.get("bound_at", "")[:19].replace("T", " ")))
    for entry_key, entry_val in bindings.get("credential", {}).items():
        rows.append(("凭证", entry_key, entry_val.get("app_name", ""), entry_val.get("bound_at", "")[:19].replace("T", " ")))

    if not rows:
        typer.echo("绑定记录: (无)\n")
        return

    typer.echo("绑定记录:")
    typer.echo(f"  {'类型':<8} {'标识':<20} {'绑定 App':<14} {'绑定时间'}")
    typer.echo("  " + "-" * 64)
    for btype, bkey, bapp, bat in rows:
        typer.echo(f"  {btype:<8} {bkey:<20} {bapp:<14} {bat}")
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
    g._save()
    typer.echo("✅ 所有绑定记录已清除")


@guard_app.command("unbind")
def cmd_guard_unbind(
    machine: str | None = typer.Option(None, "--machine", help="按机器指纹解绑"),
    ip: str | None = typer.Option(None, "--ip", help="按 IP 地址解绑"),
    credential: str | None = typer.Option(None, "--credential", help="按 API key_id 解绑"),
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
                typer.echo(f"✅ 已解除 {btype} 绑定: {bkey[:16]}...")
                removed += 1
    if machine:
        g.unbind("machine", machine)
        typer.echo(f"✅ 已解除机器绑定: {machine[:16]}...")
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
