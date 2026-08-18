from pathlib import Path

from streamlit.testing.v1 import AppTest


def workbench():
    path = Path(__file__).resolve().parents[1] / "app" / "dashboard.py"
    app = AppTest.from_file(path, default_timeout=20).run()
    assert not app.exception
    return app


def test_empty_state_and_completed_run():
    app = workbench()
    assert "Choose operating conditions" in app.info[0].value
    app.number_input[0].set_value(20)
    app.button(key="run").click().run()
    assert not app.exception
    assert len(app.metric) == 3
    assert len(app.get("plotly_chart")) == 4
    assert len(app.get("download_button")) == 2
    assert app.session_state["result"]["configuration"]["duration_seconds"] == 20


def test_missing_upload_shows_error():
    app = workbench()
    app.selectbox[0].select("CUSTOM").run()
    app.button(key="run").click().run()

    assert not app.exception
    assert "Upload a current trace" in app.error[0].value
    assert len(app.metric) == 0


def test_configuration_controls_affect_run():
    app = workbench()
    app.selectbox[0].select("FAST_CHARGE").run()
    app.selectbox[1].select(4)
    app.number_input[0].set_value(10)
    app.slider[0].set_value(0.3)
    app.checkbox[0].uncheck()
    app.number_input[1].set_value(32.0)
    app.number_input[2].set_value(34.0)
    app.number_input[3].set_value(25.0)
    app.number_input[4].set_value(2.0)
    app.number_input[5].set_value(4.0)
    app.number_input[6].set_value(1.5)
    app.button(key="run").click().run()
    assert not app.exception
    result = app.session_state["result"]
    config = result["configuration"]
    assert config["thermal_nodes"] == 4
    assert config["initial_soc"] == 0.3
    assert config["initial_temp_c"] == 32.0
    assert config["ambient_temp_c"] == 34.0
    assert config["coolant_inlet_temp_c"] == 25.0
    assert config["coolant_flow_rate_lpm"] == 2.0
    assert config["nominal_capacity_ah"] == 4.0
    assert config["thermal_derating"] is False
    assert result["timeseries"][0]["current_a"] == -6


def test_constant_current_and_zero_flow():
    app = workbench()
    app.selectbox[0].select("CONSTANT_CURRENT").run()
    app.number_input[0].set_value(10)
    app.number_input[4].set_value(0.0)
    app.number_input[7].set_value(-2.0)
    app.button(key="run").click().run()
    assert not app.exception
    result = app.session_state["result"]
    assert result["hydraulics"]["pump_power_w"] == 0
    assert result["timeseries"][0]["current_a"] == -2


def test_invalid_new_run_clears_old_results():
    app = workbench()
    app.number_input[0].set_value(5)
    app.button(key="run").click().run()
    assert len(app.metric) == 3
    app.selectbox[0].select("CUSTOM").run()
    app.button(key="run").click().run()
    assert not app.exception
    assert app.error
    assert len(app.metric) == 0
    assert len(app.get("plotly_chart")) == 0


def test_flow_comparison_and_invalid_selection():
    app = workbench()
    assert app.button(key="compare").disabled
    app.number_input[0].set_value(5)
    app.button(key="run").click().run()
    app.multiselect[0].set_value([0.0, 4.5])
    app.button(key="compare").click().run()
    assert not app.exception
    assert len(app.session_state["sweep"]["runs"]) == 2
    assert len(app.get("download_button")) == 3
    app.multiselect[0].set_value([4.5])
    app.button(key="compare").click().run()
    assert app.error
    assert len(app.get("download_button")) == 2


def test_standard_cycle_needs_no_upload_and_pack_settings_apply():
    app = workbench()
    app.selectbox[0].select("US06").run()
    app.number_input[0].set_value(20)
    app.number_input[8].set_value(100)
    app.number_input[9].set_value(50)
    app.button(key="run").click().run()
    assert not app.exception
    result = app.session_state["result"]
    assert result["pack"]["cell_count"] == 5000
    assert len(app.get("plotly_chart")) == 6
    assert result["timeseries"][-1]["speed_kph"] > 0


def test_invalid_parameter_json_is_visible():
    app = workbench()
    app.text_area[0].set_value('{"cell":{"r0_ohm":-1}}')
    app.button(key="run").click().run()
    assert not app.exception
    assert app.error
    assert len(app.metric) == 0


def test_baseline_survives_new_run_and_can_be_cleared():
    app = workbench()
    app.number_input[0].set_value(5)
    app.button(key="run").click().run()
    app.button(key="pin_baseline").click().run()
    reference = app.session_state["baseline"]["configuration"]
    app.number_input[4].set_value(0.0)
    app.button(key="run").click().run()
    assert not app.exception
    assert app.session_state["baseline"]["configuration"] == reference
    assert app.session_state["result"]["configuration"]["coolant_flow_rate_lpm"] == 0
    assert app.metric[0].delta
    app.button(key="clear_baseline").click().run()
    assert not app.exception
    assert not app.metric[0].delta
