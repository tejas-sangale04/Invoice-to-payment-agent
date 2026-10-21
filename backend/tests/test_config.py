from app.core.config import Settings


def test_firebase_project_defaults_to_google_cloud_project():
    assert Settings(google_cloud_project="real", firebase_project_id="").firebase_project == "real"


def test_firebase_project_can_differ_for_local_gemini():
    s = Settings(google_cloud_project="real", firebase_project_id="demo-invoiceflow")
    assert s.firebase_project == "demo-invoiceflow"
