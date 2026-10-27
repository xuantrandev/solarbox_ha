"""Constants and field metadata for the SolarProject integration."""

from __future__ import annotations

import re
from typing import NamedTuple

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

DOMAIN = "solarproject"

CONF_SERVER = "server"
CONF_DEVICE_ID = "device_id"
CONF_FAST_DATA_INTERVAL = "fast_data_interval"
CONF_DEVICE_NAME = "name"
CONF_SENSOR_PREFIX = "sensor_prefix"
CONF_SENSOR_PROFILE = "sensor_profile"
PROFILE_INVERTER = "inverter_bms"
PROFILE_MQ = "mq_bms"
DEFAULT_SENSOR_PROFILE = PROFILE_INVERTER

DEFAULT_SERVER = "https://ivbms.solarbox.uk"
DEFAULT_FAST_DATA_INTERVAL = 5  # seconds

DEVICE_ID_REGEX = re.compile(r"^dg-[a-zA-Z0-9]{6}$")

PLATFORMS = ["sensor", "binary_sensor", "number", "select", "switch"]

# WebSocket reconnect backoff (seconds)
WS_RECONNECT_MIN = 10
WS_RECONNECT_MAX = 60
# Server rate-limits WS connections to 20/min per IP, so never reconnect faster.

# BMS slots supported by the firmware (bms1/bms2/bms3)
BMS_SLOTS = (1, 2, 3)
BMS_MAX_CELLS = 32

# Message types pushed by the solardongleweb WebSocket server
MSG_SNAPSHOT = "snapshot"  # no "type" field — full cached state on connect
MSG_IVTDATA = "ivtdata"
MSG_BMSDATA = "bmsData"
MSG_DEVICE_STATUS = "deviceStatus"
MSG_DEVICE_INFO = "deviceInfo"
MSG_WIFI_SIGNAL = "wifiSignal"
MSG_DONGLE_SN = "dongleSNState"
MSG_LUX_SERVER_IP = "luxServerIPState"
MSG_LUX_SERVER_STATE = "luxServerState"
MSG_LUX_CLOUD_BMS_STATE = "luxCloudBMSState"
MSG_FIX_LUX_SERVER_STATE = "fixLuxServerState"
MSG_BMS_CONNECTION_STATE = "bms{}ConnectionState"


class SensorDef(NamedTuple):
    """Metadata for one sensor entity."""

    name: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    icon: str | None = None
    scale: float = 1.0
    precision: int = 3


# ── Inverter live data (data.live) ────────────────────────────────────────────
# Sensor names follow solardongle/home_senjkha.yaml and its included definitions.
INVERTER_FIELDS: dict[str, SensorDef] = {
    "vdc1": SensorDef("Ivt PV1 Voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:solar-power"),
    "vdc2": SensorDef("Ivt PV2 Voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:solar-power"),
    "vdc3": SensorDef("Ivt PV3 Voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:solar-power"),
    "pdc1": SensorDef("Ivt PV1 Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:solar-power"),
    "pdc2": SensorDef("Ivt PV2 Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:solar-power"),
    "pdc3": SensorDef("Ivt PV3 Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:solar-power"),
    "pv_power": SensorDef("Ivt PV Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:solar-power"),
    "vbat": SensorDef("Ivt Battery Voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:battery"),
    "soc": SensorDef("Ivt Battery SOC", "%", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT, "mdi:battery"),
    "fgr": SensorDef("Ivt Grid Frequency", "Hz", SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    "vgr": SensorDef("Ivt Grid Voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    "pgr": SensorDef("Ivt Grid Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:transmission-tower"),
    "pgr1": SensorDef("Ivt Pgrid1 (3 pha)", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:transmission-tower"),
    "pgr2": SensorDef("Ivt Pgrid2 (3 pha)", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:transmission-tower"),
    "pgr3": SensorDef("Ivt Pgrid3 (3 pha)", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:transmission-tower"),
    "vgr1": SensorDef("Ivt Vgrid1 (3 pha)", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    "vgr2": SensorDef("Ivt Vgrid2 (3 pha)", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    "vgr3": SensorDef("Ivt Vgrid3 (3 pha)", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    "fgr1": SensorDef("Ivt Fgrid1 (3 pha)", "Hz", SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    "fgr2": SensorDef("Ivt Fgrid2 (3 pha)", "Hz", SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    "fgr3": SensorDef("Ivt Fgrid3 (3 pha)", "Hz", SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, "mdi:sine-wave"),
    # Dongle reports negative when charging; HA exposes positive = charging.
    "pbat": SensorDef("Ivt Battery Power Lux", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:battery", -1.0),
    "bcur": SensorDef("Ivt Battery Current Lux", "A", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, "mdi:battery", -1.0),
    "pl": SensorDef("Ivt Load Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:home-lightning-bolt"),
    "pl1": SensorDef("Ivt Load L1 Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:home-lightning-bolt"),
    "pl2": SensorDef("Ivt Pload2 (3 pha)", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:home-lightning-bolt"),
    "pl3": SensorDef("Ivt Pload3 (3 pha)", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:home-lightning-bolt"),
    "po": SensorDef("Ivt Inverter Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:power"),
    "eex": SensorDef("Ivt Grid Export Today", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower"),
    "pvtd": SensorDef("Ivt PV Today Lux", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:solar-power", 0.001),
    "ltd": SensorDef("Ivt Load Today", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:home-lightning-bolt"),
    "ech": SensorDef("Ivt Battery Charge Today Lux", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:battery-charging"),
    "edch": SensorDef("Ivt Battery Discharge Today", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:battery-minus"),
    "eim": SensorDef("Ivt Grid Import Today", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower"),
}

# ── Inverter lifetime statistics (data.statistic) ─────────────────────────────
STATISTIC_FIELDS: dict[str, SensorDef] = {
    "pvall": SensorDef("Ivt PV Total Lux", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:solar-power"),
    "lall": SensorDef("Ivt Load Total", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:home-lightning-bolt"),
    "imall": SensorDef("Ivt Grid Import Total", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower"),
    "chgall": SensorDef("Ivt Battery Charge Total", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:battery-charging"),
    "dchgall": SensorDef("Ivt Battery Discharge Total", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:battery-minus"),
    "exall": SensorDef("Ivt Grid Export Total", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower"),
    "dctemp": SensorDef("Ivt DC Temp", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer"),
    "actemp": SensorDef("Ivt AC Temp", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer"),
    "mxchg": SensorDef("Ivt Max Charge Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:battery-charging"),
    "mxdchg": SensorDef("Ivt Max Discharge Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:battery-minus"),
}

# ── WiFi signal (topic <deviceId>/sensor/wifi_signal/state) ──────────────────
WIFI_SIGNAL_DEF = SensorDef(
    "Wifi Signal", "dBm", SensorDeviceClass.SIGNAL_STRENGTH,
    SensorStateClass.MEASUREMENT, "mdi:wifi",
)

# ── BMS scalar fields (per slot; key is the raw JSON key inside bmsN) ────────
# Names follow home_senjkha.yaml and release_senjkha.yaml: "bms1 total
# voltage", "bms1 state of charge", "bms1 temperature sensor 1", ...
BMS_FIELDS: dict[str, SensorDef] = {
    "soc": SensorDef("bms{n} state of charge", "%", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT, "mdi:battery"),
    "vbat": SensorDef("bms{n} total voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, "mdi:battery", 0.1),
    "cur": SensorDef("bms{n} current", "A", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, "mdi:battery", 0.1),
    "p": SensorDef("bms{n} power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:battery"),
    # Derived from signed p (W): positive charging, negative discharging.
    "charging_power": SensorDef("bms{n} charging power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:battery-charging"),
    "discharging_power": SensorDef("bms{n} discharging power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, "mdi:battery-minus"),
    "cap": SensorDef("bms{n} capacity remaining", "Ah", None, SensorStateClass.MEASUREMENT, "mdi:battery", 0.001),
    "cycle": SensorDef("bms{n} charging cycles", None, None, SensorStateClass.MEASUREMENT, "mdi:counter"),
    "t0": SensorDef("bms{n} temperature sensor 1", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer", 0.1),
    "t1": SensorDef("bms{n} temperature sensor 2", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer", 0.1),
    "t2": SensorDef("bms{n} temperature sensor 3", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer", 0.1),
    "t3": SensorDef("bms{n} temperature sensor 4", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer", 0.1),
    "t4": SensorDef("bms{n} power tube temperature", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer", 0.1),
    "t5": SensorDef("bms{n} temperature sensor 5", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, "mdi:thermometer", 0.1),
}

BMS_CELL_DEF = SensorDef(
    "bms{n} cell voltage {i}",
    "V",
    SensorDeviceClass.VOLTAGE,
    SensorStateClass.MEASUREMENT,
    "mdi:battery",
    0.001,
)

BMS_MAC_TEXT_DEF = SensorDef(
    "BMS{n} MAC", None, None, None, "mdi:qrcode",
)

# ── Text fields (read-only strings surfaced as string sensors) ───────────────
TEXT_FIELDS: dict[str, SensorDef] = {
    "ivttype": SensorDef("Ivt Type", None, None, None, "mdi:inverter"),
    "dongle_sn": SensorDef("Dongle SN", None, None, None, "mdi:qrcode"),
    "lux_server_ip": SensorDef("Lux Server IP", None, None, None, "mdi:ip-network"),
    "device_info_name": SensorDef("Device Name", None, None, None, "mdi:devices"),
    "device_info_version": SensorDef("Firmware Version", None, None, None, "mdi:memory"),
    "device_info_project_name": SensorDef("Project Name", None, None, None, "mdi:devices"),
    "device_info_project_version": SensorDef("Project Version", None, None, None, "mdi:memory"),
    "device_info_ip": SensorDef("IP Address", None, None, None, "mdi:ip-network"),
    "device_info_mac": SensorDef("Device MAC", None, None, None, "mdi:qrcode"),
}

# Binary sensor keys stored in coordinator.data
BIN_ONLINE = "online"
BIN_LUX_SERVER = "lux_server_state"
BIN_FIX_LUX_SERVER = "fix_lux_server_state"
BIN_BMS_CONNECTED = "bms{n}_connected"
BIN_BMS_CHG = "bms{n}_chg"
BIN_BMS_DISCHG = "bms{n}_dischg"


# MQ uses the same wire fields as the inverter, but native HA names/units.
# Prefix keys with mq_ in HA so choosing a different profile cannot reuse an
# inverter entity's history for an unrelated measurement.
MQ_FIELDS: dict[str, SensorDef] = {
    "mq_dctemp": SensorDef("MQ Temperature", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    "mq_vdc1": SensorDef("MQ PV Voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT),
    "mq_idc1": SensorDef("MQ PV Current", "A", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT),
    "mq_vbat": SensorDef("MQ Battery Voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT),
    "mq_bcur": SensorDef("MQ Battery Current", "A", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, scale=-1),
    "mq_pdc1": SensorDef("MQ PV Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    "mq_pbat": SensorDef("MQ Battery Power", "W", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, scale=-1),
    "mq_pvtd": SensorDef("MQ PV Energy Today", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, scale=0.001),
    "mq_pvall": SensorDef("MQ PV Energy Total", "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING),
    "mq_status_code": SensorDef("MQ Status Code", state_class=SensorStateClass.MEASUREMENT),
    "mq_efficiency": SensorDef("MQ MPPT Efficiency", "%", state_class=SensorStateClass.MEASUREMENT),
}
# Preserve native power precision locally while retaining integer cloud payloads.
MQ_NATIVE_POWER_KEYS = {"mq_pdc1": "mq_native_pv_power", "mq_pbat": "mq_native_battery_power"}
MQ_TEXT_FIELDS = {"mq_status_text": SensorDef("MQ MPPT Status")}
MQ_BMS_NATIVE_FIELDS: dict[str, SensorDef] = {
    "min_voltage_cell": SensorDef("bms{n} min voltage cell", state_class=SensorStateClass.MEASUREMENT),
    "max_voltage_cell": SensorDef("bms{n} max voltage cell", state_class=SensorStateClass.MEASUREMENT),
    "delta_cell_voltage": SensorDef("bms{n} delta cell voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT),
    "average_cell_voltage": SensorDef("bms{n} average cell voltage", "V", SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, precision=4),
    "design_capacity": SensorDef("bms{n} total battery capacity setting", "Ah", state_class=SensorStateClass.MEASUREMENT),
    "balancing_current": SensorDef("bms{n} balancing current", "A", SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT),
    "cycle_charge": SensorDef("bms{n} total charging cycle capacity", "Ah", state_class=SensorStateClass.MEASUREMENT),
    **{f"cell_resistance_{i}": SensorDef(f"bms{{n}} cell resistance {i}", "Ω", state_class=SensorStateClass.MEASUREMENT) for i in range(1, 17)},
}
MQ_BMS_NATIVE_TEXT_FIELDS = {
    key: SensorDef("bms{n} " + name)
    for key, name in (
        ("errors", "errors"), ("total_runtime_formatted", "total runtime formatted"),
        ("software_version", "software version"), ("hardware_version", "hardware version"),
    )
}
MQ_DONGLE_FIELDS = {
    "dongle_temperature": SensorDef("Dongle Internal Temperature", "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
    "dongle_uptime": SensorDef("Dongle Uptime", "s", SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT),
}


def is_mq_profile(entry):
    return entry.data.get(CONF_SENSOR_PROFILE, DEFAULT_SENSOR_PROFILE) == PROFILE_MQ


def mq_native_fields(text=False):
    """Native-unit supplemental fields, disjoint from raw scaled BMS keys."""
    fields = MQ_BMS_NATIVE_TEXT_FIELDS if text else MQ_BMS_NATIVE_FIELDS
    result = {} if text else dict(MQ_DONGLE_FIELDS)
    for slot in BMS_SLOTS:
        for key, spec in fields.items():
            result[f"bms{slot}_native_{key}"] = spec._replace(name=spec.name.format(n=slot))
    return result


# Read native BMS fields locally: cloud cap and temperature indices are not
# equivalent to the native firmware's capacity-remaining/temperature sensors.
BMS_NATIVE_KEYS = {
    "soc": "state_of_charge",
    "vbat": "total_voltage",
    "cur": "current",
    "p": "power",
    "cap": "capacity_remaining",
    "cycle": "charging_cycles",
    "t0": "temperature_sensor_1",
    "t1": "temperature_sensor_2",
    "t2": "temperature_sensor_3",
    "t3": "temperature_sensor_4",
    "t4": "mosfet_temperature"
}


def home_native_keys():
    keys = set(MQ_NATIVE_POWER_KEYS.values()) | set(mq_native_fields()) | set(mq_native_fields(text=True))
    for slot in BMS_SLOTS:
        fields = set(BMS_NATIVE_KEYS.values()) | {"mac", "balancing", "charging", "discharging"}
        fields.update(f"cell_voltage_{i}" for i in range(1, 17))
        keys.update(f"bms{slot}_native_{field}" for field in fields)
    return keys
