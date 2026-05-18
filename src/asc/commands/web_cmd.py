"""asc web command — start local Web UI server."""
from __future__ import annotations
import threading
import webbrowser
import typer


def cmd_web(
    port: int = typer.Option(8080, "--port", "-p", help="监听端口（默认 8080）"),
    no_open: bool = typer.Option(False, "--no-open", help="不自动打开浏览器"),
    host: str = typer.Option("127.0.0.1", "--host", help="监听地址（默认 127.0.0.1）"),
):
    """启动本地 Web UI 服务器。

    \b
    Example:
        asc web
        asc web --port 9090
        asc web --no-open
    """
    import uvicorn
    from asc.web.server import create_app

    open_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{open_host}:{port}"
    typer.echo(f"🌐 启动 Web UI：{url}")

    if not no_open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")
