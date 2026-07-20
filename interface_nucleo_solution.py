# Copyright University of Bologna - ETH Zurich 2026
# Licensed under Apache v2.0 see LICENSE for details.
#
# SPDX-License-Identifier: Apache-2.0

"""
Interface for the NUCLEO F401RET6 board and X-NUCLEO-IKS01A2 sensor expansion board.
The device is connected to the host PC via USB, and streams IMU data over a virtual COM port.
The IMU data comprises accelerometer and gyroscope readings; the two
packet types are demultiplexed by their header byte / total length (the data
source frames packets from the ``packetSize`` list of (header, size) tuples):

  0xAA → ACC packet (211 bytes)  ── 4 samples × 3 channels
  0xBB → GYRO packet (136 bytes) ── 4 samples × 3 channels
"""

import numpy as np

# ── Accelerometer (ACC) decode constants ───────────────────────────────────
_ACC_SAMP = 4  # number of ACC samples per packet
_ACC_CH = 3  # number of ACC channels
_ACC_BYTES_CH = 4  # number of bytes per ACC sample (float32, little-endian)
_ACC_BYTES = _ACC_SAMP * _ACC_CH * _ACC_BYTES_CH
_ACC_FS = 104.0  # Hz, per channel

# ── Gyroscope (GYRO) decode constants ──────────────────────────────────────
_GYRO_SAMP = 4  # number of GYRO samples per packet
_GYRO_CH = 3  # number of GYRO channels
_GYRO_BYTES_CH = 4  # number of bytes per GYRO sample (float32, little-endian)
_GYRO_BYTES = _GYRO_SAMP * _GYRO_CH * _GYRO_BYTES_CH
_GYRO_FS = 104.0  # Hz, per channel

# ── BLE framing constants ──────────────────────────────────────────────────
_ACC_HEADER = 0xAA
_GYRO_HEADER = 0xBB
_ACC_PACKET_SIZE = _ACC_BYTES + 1  # extra byte for header
_GYRO_PACKET_SIZE = _GYRO_BYTES + 1  # extra byte for header

packetSize: list[tuple[int, int]] = [
    (_ACC_HEADER, _ACC_PACKET_SIZE),
    (_GYRO_HEADER, _GYRO_PACKET_SIZE),
]
"""List of (header_byte, packet_size) tuples."""

startSeq: list[bytes | float] = [b"b"]
"""Commands to start streaming."""

stopSeq: list[bytes | float] = [b"e"]
"""Commands to stop streaming."""

sigInfo: dict = {
    "acc": {"fs": _ACC_FS, "nCh": _ACC_CH, "extras": {"type": "time-series"}},
    "gyro": {"fs": _GYRO_FS, "nCh": _GYRO_CH, "extras": {"type": "time-series"}},
}
"""Signal definitions."""


def decodeFn(data: bytes) -> dict[str, np.ndarray]:
    """
    Decode one packet from the combined ACC + GYRO stream.

    Header 0xAA → ACC packet.
    Header 0xBB → GYRO packet.

    Returns a dict keyed by every signal in ``sigInfo``; the signals not carried
    by this packet are left as empty (0-length) arrays.
    """
    results = {
        "acc": np.empty((0, _ACC_CH), dtype=np.float32),
        "gyro": np.empty((0, _GYRO_CH), dtype=np.float32),
    }

    # Read header
    header = data[0]

    # Accelerometer case
    if header == _ACC_HEADER:
        acc = np.frombuffer(data[1 : 1 + _ACC_BYTES], dtype="<f4").reshape(
            _ACC_SAMP, _ACC_CH
        )
        results["acc"] = acc
        return results

    # Gyroscope case
    if header == _GYRO_HEADER:
        gyro = np.frombuffer(data[1 : 1 + _GYRO_BYTES], dtype="<f4").reshape(
            _GYRO_SAMP, _GYRO_CH
        )
        results["gyro"] = gyro
        return results

    raise ValueError(f"Unknown packet header: {header:#04x}")
