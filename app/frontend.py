from pathlib import PurePosixPath
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    """SPA routes fall back to the entry point; missing assets remain 404."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or PurePosixPath(path).suffix or path.startswith(('assets/', 'pdfjs/')):
                raise
            return await super().get_response('index.html', scope)
