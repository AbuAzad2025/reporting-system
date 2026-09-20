"""Real comprehensive main routes tests."""

class TestMainRealRoutes:
    def test_main_index(self, client):
        r = client.get("/")
        assert r.status_code == 200
    
    def test_main_login_redirect(self, client):
        r = client.get("/login")
        assert r.status_code in (200, 302)
    
    def test_main_logout(self, client):
        r = client.get("/logout")
        assert r.status_code in (200, 302)
