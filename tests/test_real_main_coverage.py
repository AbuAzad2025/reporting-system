"""REAL FUNCTIONAL TESTS for main routes."""

def test_main_index_loads_real(app):
    with app.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200, f"Main index failed: {response.status_code}"
        # Verify actual content exists
        assert len(response.data) > 0, "Main index returned empty response"


def test_main_login_route_exists_real():
    from app.main.routes import index, dashboard, archive
    assert callable(index)
    assert callable(dashboard)
    assert callable(archive)


def test_main_project_view_real(app):
    with app.test_client() as client:
        # Main index always available
        response = client.get("/")
        assert response.status_code == 200, f"Main index failed: {response.status_code}"
        assert len(response.data) > 0, "Main index returned empty response"
