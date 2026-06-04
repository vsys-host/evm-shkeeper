from app import celery, create_app  # noqa: F401


app = create_app()
app.app_context().push()
