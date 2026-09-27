"""Thin entry point — canonical app lives in /app factory (Flask pattern)."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    import os

    # This is the Flask development server: it is not a production server and
    # must never be exposed to a network it was not asked to serve.
    #
    # It used to hardcode host="0.0.0.0" and debug=True. That bound the
    # Werkzeug interactive debugger to every interface, so anyone who could
    # reach the port could reach a debugger capable of executing code. Debug is
    # now opt-in via FLASK_DEBUG and the interface is loopback unless HOST says
    # otherwise; production traffic belongs to gunicorn (see requirements.txt).
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in (
        "1", "true", "yes", "on")
    app.run(host=host, port=port, debug=debug)
