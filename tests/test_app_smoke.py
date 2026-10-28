"""Headless check that the Streamlit UI renders and a demo run works."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_runs_demo_end_to_end():
    at = AppTest.from_file(APP, default_timeout=90).run()
    assert not at.exception
    at.selectbox(key="extractor_label").set_value("Rules only (free)").run()
    at.radio(key="method").set_value("Load a sample file").run()
    at.button(key="run_btn").click().run()
    assert not at.exception
    assert [m.value for m in at.metric] == ["8", "3", "1", "2", "2"]


def test_app_rejects_bad_input_without_crashing():
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.text_area(key="names_text").set_value("http://evil.com\nA").run()
    assert not at.exception
    assert at.button(key="run_btn").disabled
