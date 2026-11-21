from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.frontend import FrontendFiles


def test_spa_routes_and_missing_assets(tmp_path):
    (tmp_path / 'index.html').write_text('<html>Science Extract</html>')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'app.js').write_text('console.log("app")')
    app = FastAPI()
    app.mount('/frontend', FrontendFiles(directory=tmp_path, html=True))
    client = TestClient(app)
    for path in ('/frontend/', '/frontend/login', '/frontend/corpora/123/documents'):
        response = client.get(path)
        assert response.status_code == 200
        assert 'Science Extract' in response.text
    assert client.get('/frontend/assets/app.js').status_code == 200
    for path in ('/frontend/assets/missing.js', '/frontend/pdfjs/missing.wasm', '/frontend/.env', '/api/v1/missing'):
        assert client.get(path).status_code == 404
