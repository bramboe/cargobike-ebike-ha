"""Additive MQTT discovery; existing entity IDs and topics stay unchanged."""
import json


def publish(client, *, node, prefix, topic, availability, device):
    sensors = (
        ("service_days", "Estimated days to service", "d", "duration"),
        ("service_weeks", "Estimated weeks to service", "weeks", None),
        ("service_rides", "Estimated rides to service", "rides", None),
        ("km_per_ride", "Average observed ride distance", "km", "distance"),
        ("km_per_day", "Average daily distance", "km/d", None),
        ("rides_per_week", "Observed rides per week", "rides/week", None),
        ("local_battery_soh", "Battery health (BLE)", "%", None),
        ("local_battery_cycles", "Battery charge cycles (BLE)", "cycles", None),
        ("local_battery_voltage", "Battery voltage (BLE)", "V", "voltage"),
        ("local_battery_temperature", "Battery temperature (BLE)", "°C", "temperature"),
        ("local_motor_temperature", "Motor PCB temperature (BLE)", "°C", "temperature"),
        ("local_battery_remaining_wh", "Battery remaining energy (BLE)", "Wh", "energy_storage"),
        ("local_battery_usable_wh", "Battery usable energy (BLE)", "Wh", "energy_storage"),
    )
    for key, name, unit, device_class in sensors:
        cfg = {"name": name, "unique_id": f"{node}_{key}", "state_topic": topic,
               "value_template": "{{ value_json.get('%s') }}" % key,
               "unit_of_measurement": unit, "device": device,
               "availability_topic": availability, "state_class": "measurement"}
        if device_class:
            cfg["device_class"] = device_class
        client.publish(f"{prefix}/sensor/{node}/{key}/config", json.dumps(cfg), retain=True)
    # Diagnostic entities carry full, timestamped evidence as attributes.
    for key, name, template, attr in (
        ("reader_connection", "Reader connection", "{{ value_json.connection.state }}", "connection"),
        ("service_forecast", "Service forecast", "{{ value_json.forecast.forecast_status }}", "forecast"),
        ("component_inventory", "Component inventory", "{{ value_json.components | count }}", "components"),
        ("ble_capabilities", "BLE diagnostic capabilities", "{{ value_json.capabilities | count }}", "capabilities"),
    ):
        cfg = {"name": name, "unique_id": f"{node}_{key}", "state_topic": topic,
               "value_template": template, "device": device, "entity_category": "diagnostic",
               "json_attributes_topic": topic,
               "json_attributes_template": "{{ value_json.%s | tojson }}" % attr,
               "availability_topic": availability}
        client.publish(f"{prefix}/sensor/{node}/{key}/config", json.dumps(cfg), retain=True)
    for key, name in (("service_soon", "Service due soon"),
                      ("battery_temperature_warning", "Battery temperature warning"),
                      ("battery_voltage_warning", "Battery voltage warning")):
        cfg = {"name": name, "unique_id": f"{node}_{key}", "state_topic": topic,
               "value_template": "{{ 'ON' if value_json.get('%s') == true else 'OFF' if value_json.get('%s') == false else 'None' }}" % (key, key),
               "payload_on": "ON", "payload_off": "OFF", "device_class": "problem",
               "device": device, "availability_topic": availability}
        client.publish(f"{prefix}/binary_sensor/{node}/{key}/config", json.dumps(cfg), retain=True)
    client.publish(f"{prefix}/binary_sensor/{node}/receiver_problem/config", json.dumps({
        "name": "Bluetooth receiver problem", "unique_id": f"{node}_receiver_problem",
        "state_topic": topic, "device_class": "problem", "device": device,
        "value_template": "{{ 'ON' if value_json.receiver_health == 'unavailable' else 'OFF' }}",
        "payload_on": "ON", "payload_off": "OFF", "availability_topic": availability,
        "entity_category": "diagnostic"}), retain=True)
