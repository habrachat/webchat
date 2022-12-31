import aiohttp
from aiohttp import web, WSCloseCode
import asyncio
import asyncssh
from contextlib import suppress


TIMEOUT = 120


last_user_id = 0


async def http_handler(request):
    return web.FileResponse("index.html")


async def websocket_handler(request):
    global last_user_id

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    last_user_id += 1
    options = asyncssh.SSHClientConnectionOptions(
        preferred_auth=["keyboard-interactive", "none"],
        public_key_auth=False,
        kbdint_auth=True
    )
    async with asyncssh.connect("habra.chat", username=f"Web{last_user_id}", password="", options=options) as conn:
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


def create_app():
    app = web.Application()
    app.add_routes([
        web.get("/", http_handler),
        web.get("/ws", websocket_handler),
    ])
    return app


if __name__ == "__main__":
    web.run_app(create_app())
