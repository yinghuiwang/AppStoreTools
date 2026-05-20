"""asc web command — start local Web UI server."""
from __future__ import annotations

import threading
import webbrowser

import typer

from asc.web.daemon import get_status, start_background, stop

web_app = typer.Typer(help="本地 Web UI", invoke_without_command=True)


def _open_browser(url: str) -> None:
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()


def _run_foreground(host: str, port: int, no_open: bool) -> None:
    import uvicorn
    from asc.web.server import create_app

    open_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{open_host}:{port}"
    typer.echo(f"🌐 启动 Web UI（前台）：{url}")

    if not no_open:
        _open_browser(url)

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


@web_app.callback(invoke_without_command=True)
def cmd_web(
    ctx: typer.Context,
    port: int = typer.Option(8080, "--port", "-p", help="监听端口（默认 8080）"),
    no_open: bool = typer.Option(False, "--no-open", help="不自动打开浏览器"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址（默认 127.0.0.1）"),
    foreground: bool = typer.Option(
        False,
        "--foreground",
        "-f",
        help="前台运行（阻塞终端，调试用）",
    ),
):
    """启动本地 Web UI 服务器（默认后台运行）。

    \b
    Example:
        asc web
        asc web --port 9090
        asc web --foreground
        asc web status
        asc web stop
    """
    if ctx.invoked_subcommand is not None:
        return

    if foreground:
        _run_foreground(host, port, no_open)
        return

    result = start_background(host, port)
    status = result.get("status")

    if status == "already_running":
        url = result["url"]
        typer.echo(f"✅ Web UI 已在运行：{url}  (PID {result['pid']})")
        typer.echo(f"   日志：{result['log']}")
        if not no_open:
            _open_browser(url)
        return

    if status == "error":
        typer.echo(f"❌ 启动失败：{result.get('message', 'unknown error')}", err=True)
        raise typer.Exit(1)

    url = result["url"]
    typer.echo(f"🌐 Web UI 已在后台启动：{url}")
    typer.echo(f"   PID：{result['pid']}")
    typer.echo(f"   日志：{result['log']}")
    typer.echo("   停止：asc web stop")

    if not no_open:
        _open_browser(url)


@web_app.command("status")
def cmd_web_status():
    """查看 Web UI 后台进程状态。"""
    status = get_status()
    if not status.get("running"):
        if status.get("stale"):
            typer.echo("Web UI 未运行（已清理失效状态）")
        else:
            typer.echo("Web UI 未运行")
        return

    typer.echo(f"✅ Web UI 运行中：{status['url']}")
    typer.echo(f"   PID：{status['pid']}")
    typer.echo(f"   工作目录：{status.get('cwd', '')}")
    typer.echo(f"   日志：{status.get('log', '')}")


@web_app.command("stop")
def cmd_web_stop():
    """停止后台 Web UI 进程。"""
    result = stop()
    status = result.get("status")

    if status == "not_running":
        typer.echo("Web UI 未运行")
        return

    if status == "error":
        typer.echo(f"❌ 停止失败：{result.get('message', 'unknown error')}", err=True)
        raise typer.Exit(1)

    forced = "（强制）" if result.get("forced") else ""
    typer.echo(f"✅ Web UI 已停止{forced}  (PID {result.get('pid', '')})")
