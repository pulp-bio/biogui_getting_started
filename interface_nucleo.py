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

  0x55 → ACC packet (211 bytes)   ── 4 samples × 16 channels
  0xAA → GYRO packet (136 bytes)   ── 64 PCM samples, 16 kHz mono

EMG packet layout is byte-for-byte identical to the EEG packet (211 bytes,
EXG_PCK_LNGTH); only the start/stop commands differ (37/38 vs 18/19):
  [0]       0x55  header
  [1:3]     counter (uint16 LE)
  [3:7]     timestamp µs (uint32 LE)
  [7:57]    sample 1: ADS_A[0:24] + ADS_B[0:24] + counter_extra + 0x00
  [57:107]  sample 2
  [107:157] sample 3
  [157:207] sample 4
  [207:210] metadata (board_id, sync_pulse_count, reserved)
  [210]     0xAA  trailer

MIC packet layout (136 bytes, MIC_PCKT_SIZE):
  [0]       0xAA  header
  [1:3]     counter (uint16 LE)
  [3:7]     timestamp µs (uint32 LE)
  [7:135]   64 PCM samples × 2 bytes (int16 LE each)
  [135]     0x55  trailer

Each ADS block is 8 channels × 3 bytes (big-endian 24-bit 2's complement).
Firmware default: gain = 6, vRef = 2.5 V.

The firmware has no dedicated synced EMG+MIC command, so EMG and MIC are started
with their individual commands (37 then 26); START_EMG_STREAMING resets the
packet counters for the session.
See ``src_NRF/BLE_PACKET_STRUCTURE.md`` for the authoritative packet reference.
"""

import numpy as np

# ── Accelerometer (ACC) decode constants ───────────────────────────────────
_ACC_SAMP = 4  # ACC samples per packet
_ACC_CH = 3  # channels
_ACC_BYTES_CH = 4  # 32-bit
_ACC_BYTES = _ACC_SAMP * _ACC_CH * _ACC_BYTES_CH
_ACC_FS = 104.0  # Hz, per channel

# ── Gyroscope (GYRO) decode constants ──────────────────────────────────────
_GYRO_SAMP = 4  # GYRO samples per packet
_GYRO_CH = 3  # channels
_GYRO_BYTES_CH = 4  # 32-bit
_GYRO_BYTES = _GYRO_SAMP * _GYRO_CH * _GYRO_BYTES_CH
_GYRO_FS = 104.0  # Hz, per channel

# ── BLE framing constants ──────────────────────────────────────────────────
_ACC_HEADER = 0xAA
_GYRO_HEADER = 0xBB
_ACC_PACKET_SIZE = _ACC_BYTES + 1
_GYRO_PACKET_SIZE = _GYRO_BYTES + 1

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

    Header 0x55 → ACC packet.
    Header 0xAA → GYRO packet.

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

    if header == _GYRO_HEADER:
        # Handle GYRO packet
        gyro = np.frombuffer(data[1 : 1 + _GYRO_BYTES], dtype="<f4").reshape(
            _GYRO_SAMP, _GYRO_CH
        )
        results["gyro"] = gyro
        return results

    raise ValueError(f"Unknown packet header: {header:#04x}")
