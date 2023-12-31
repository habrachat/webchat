import aiohttp
from aiohttp import web, WSCloseCode
import asyncio
import asyncssh
import base64
from contextlib import suppress
import sys


TIMEOUT = 120


last_user_id = 0


async def http_handler(request):
    return web.FileResponse("index.html")


async def websocket_handler(request):
    global last_user_id

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    info = await ws.receive_str()
    key, nick = map(base64.b64decode, info.split(",", 1))

    last_user_id += 1
    options = asyncssh.SSHClientConnectionOptions(
        client_keys=[asyncssh.import_private_key(key)],
        agent_path=""
    )
    async with asyncssh.connect(
        "habra.chat",
        username=nick.decode() or f"Web{last_user_id}",
        password="",
        options=options
    ) as conn:
        async with conn.create_process("", encoding=None) as process:
            async def ssh_to_ws():
                while True:
                    chunk = await process.stdout.read(4096)
                    if not chunk:
                        break
                    await ws.send_bytes(chunk)

            abort_event = asyncio.Event()

            async def abort():
                await asyncio.sleep(TIMEOUT)
                abort_event.set()

            async def ws_to_ssh():
                abort_task = asyncio.create_task(abort())
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        process.stdin.write(msg.data)
                    elif msg.type == aiohttp.WSMsgType.TEXT and msg.data.strip():
                        cmd, *args = msg.data.split()
                        if cmd == "resize" and len(args) == 2:
                            cols, rows = args
                            if 0 < len(cols) < 10 and 0 < len(rows) < 10 and cols.isdigit() and rows.isdigit():
                                cols = int(cols)
                                rows = int(rows)
                                process.change_terminal_size(cols, rows)
                    abort_task.cancel()
                    abort_task = asyncio.create_task(abort())
                abort_task.cancel()

            loop = asyncio.get_running_loop()
            tasks = [
                loop.create_task(ssh_to_ws()),
                loop.create_task(ws_to_ssh()),
                loop.create_task(abort_event.wait())
            ]
            done_first, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for coro in done_first:
                coro.result()
            for p in pending:
                p.cancel()
                with suppress(asyncio.CancelledError):
                    await p

    return ws


def create_app(argv):
    app = web.Application()
    app.add_routes([
        web.get("/chat", http_handler),
        web.get("/chat/", http_handler),
        web.get("/chat/ws", websocket_handler),
    ])
    return app


if __name__ == "__main__":
    web.run_app(create_app(sys.argv[1:]))
