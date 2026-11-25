"""Count streamed bodies, including requests without Content-Length."""
from starlette.exceptions import HTTPException
from .config import settings


class RequestBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        received = 0
        maximum = settings().max_file_mb * settings().max_upload_files * 1024 * 1024 + 100000

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > maximum:
                    raise HTTPException(413, 'Streamed request body too large')
            return message

        await self.app(scope, bounded_receive, send)
