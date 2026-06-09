"""
Integration tests for tv-stretch-node firmware using pytest-embedded.

Requires: pytest-embedded, pytest-embedded-serial-esp

Usage:
    pytest firmware/tv-stretch-node/pytest_tv_stretch_node.py \
        --embedded-services esp,idf \
        --app firmware/tv-stretch-node/build

These tests flash the firmware to a connected ESP32-C3 and verify
basic functionality via serial output.
"""

import re

import pytest


@pytest.mark.esp32c3
def test_firmware_boot_and_hello(dut):
    """Verify firmware boots and prints the initialization sequence."""
    boot_msgs = [
        "NVS init",
        "STA start",
        "CEC on GPIO",
    ]
    for msg in boot_msgs:
        dut.expect(re.compile(msg.encode()), timeout=15)


@pytest.mark.esp32c3
def test_firmware_heartbeat(dut):
    """Verify the firmware sends periodic heartbeats."""
    dut.expect_exact(b"heartbeat", timeout=30)


@pytest.mark.esp32c3
def test_firmware_version_reported(dut):
    """Verify the firmware version is reported on startup."""
    match = dut.expect(re.compile(rb'"fw":"([^"]+)"'), timeout=15)
    version = match.group(1).decode()
    assert version, "Firmware version should not be empty"
    assert version.count(".") >= 2, f"Version {version} should be semver"


@pytest.mark.esp32c3
def test_cec_pulse_command_handling(dut):
    """Verify we can send a CEC broadcast ping command and get an ack."""
    import json

    cmd = {
        "v": 1,
        "type": "command_batch",
        "batch_id": "pytest-batch-001",
        "commands": [
            {"cmd": "cec_broadcast_ping", "payload": {"room": "test"}}
        ],
    }
    # Simulate the server sending a command
    dut.serial.write(json.dumps(cmd).encode() + b"\n")
    ack = dut.expect(re.compile(rb'"batch_id":"pytest-batch-001","ok":true'), timeout=10)
    assert ack is not None


@pytest.mark.esp32c3
def test_noop_command_handling(dut):
    """Verify noop commands are handled without error."""
    import json

    cmd = {
        "v": 1,
        "type": "command_batch",
        "batch_id": "pytest-noop-001",
        "commands": [
            {"cmd": "noop", "payload": {"phase": "test"}}
        ],
    }
    dut.serial.write(json.dumps(cmd).encode() + b"\n")
    ack = dut.expect(re.compile(rb'"batch_id":"pytest-noop-001","ok":true'), timeout=10)
    assert ack is not None
