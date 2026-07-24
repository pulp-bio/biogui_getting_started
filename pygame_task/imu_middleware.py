# Copyright University of Bologna - ETH Zurich 2026
# Licensed under Apache v2.0 see LICENSE for details.
#
# SPDX-License-Identifier: Apache-2.0

"""
This module reads data from the BioGUI, runs the classification algorithm,
and sends the prediction to PyGame.


Copyright 2026 University of Bologna - ETH Zurich

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import logging
import os
import socket
import struct
from enum import Enum

import numpy as np
from scipy import signal
from skops import io as sio

type Endpoint = str | tuple[str, int]


label_map = {0: "REST", 1: "RIGHT", 2: "LEFT", 3: "UP", 4: "DOWN"}
label_inv_map = {"REST": 0, "RIGHT": 1, "LEFT": 2, "UP": 3, "DOWN": 4}


def recvall(sock: socket.socket, n_bytes: int) -> bytes:
    """
    Receive exactly n bytes.

    Parameters
    ----------
    sock : socket
        Instance of socket.
    n_bytes : int
        Number of bytes to read.

    Returns
    -------
    bytes
        Data packet received.

    Raises
    ------
    ConnectionError
        If the connection is closed by the peer before reading all the bytes.
    """
    data = bytearray()
    while len(data) < n_bytes:
        packet = sock.recv(n_bytes - len(data))
        if not packet:
            raise ConnectionError(
                f"Expected {n_bytes} bytes, got only {len(data)} before socket closed"
            )
        data.extend(packet)
    return bytes(data)


def parse_endpoint(endpoint: str) -> Endpoint:
    """
    Parse an endpoint string into a Unix socket or address:port pair.

    Arguments
    ---------
    endpoint : str
        Endpoint string, either a Unix socket path or "address:port" pair.

    Returns
    -------
    Endpoint
        Parsed endpoint.
    """
    if ":" in endpoint:
        address, port_str = endpoint.split(":")
        try:
            port = int(port_str)
        except ValueError:
            raise ValueError(f"Invalid port number: {port_str}")
        return (address, port)
    else:
        return endpoint


class State(Enum):
    """State of the middleware."""

    CONNECT = 0
    RUN = 1


class ServerRelay:
    """
    Server relay.

    Parameters
    ----------
    data_endpoint : Endpoint
        Endpoint for the data streaming service, either a Unix socket path or an
        address:port pair for TCP.
    cmd_endpoint : Endpoint
        Endpoint for the command service, either a Unix socket path or an
        address:port pair for TCP.
    subj : str
        Subject identifier.
    exp : str
        Experiment name.
    model_path : str or None
        Path to the pre-trained model: if the experiment is specified, this argument is ignored;
        if the experiment is not specified, this argument is mandatory.

    Attributes
    ----------
    _n_ch_acc : int
        Number of acceleration channels.
    _n_ch_gyro : int
        Number of gyroscope channels.
    _fs : int
        Sampling rate.
    _win_size : int
        Size of each window received.
    _n_bytes : int
        Number of bytes per window.
    _data_server : socket
        Server socket for the data streaming service.
    _cmd_server : socket
        Server socket for the command service.
    _model : SVC
        SVM model.
    _zi_pitch : np.ndarray
        Filter state for pitch.
    _zi_roll : np.ndarray
        Filter state for roll.
    """

    def __init__(
        self,
        data_endpoint: Endpoint,
        cmd_endpoint: Endpoint,
        model_path: str,
    ) -> None:
        self._n_ch_acc, self._n_ch_gyro = 3, 3
        self._n_out = 4
        self._fs = 104
        self._win_size = int(round(200 / 1000 * self._fs))  # 200 ms
        self._n_bytes = (
            self._win_size * (self._n_ch_acc + self._n_ch_gyro) * 4
        )  # float32
        self._state = State.CONNECT

        # 1. Set up server sockets
        # 1.1. For receiving data
        match data_endpoint:
            case str() as unix_path:
                if os.path.exists(unix_path):
                    os.remove(unix_path)
                self._emg_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            case (str(), int()):
                self._emg_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._emg_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            case _:
                raise ValueError("Invalid endpoint type.")
        self._emg_server.bind(data_endpoint)
        self._emg_server.listen(1)
        logging.info("Listening for upstream on %s...", data_endpoint)
        # 1.2. For sending commands
        match cmd_endpoint:
            case str() as unix_path:
                if os.path.exists(unix_path):
                    os.remove(unix_path)
                self._cmd_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            case (str(), int()):
                self._cmd_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._cmd_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            case _:
                raise ValueError("Invalid endpoint type.")
        self._cmd_server.bind(cmd_endpoint)
        self._cmd_server.listen(1)
        logging.info("Listening for downstream on %s...", cmd_endpoint)

        # 2. Load model
        self._model = sio.load(model_path)

        # 3. Filter parameters
        self._zi_pitch = np.zeros(1)
        self._zi_roll = np.zeros(1)

    def __del__(self) -> None:
        self._cmd_server.close()
        self._emg_server.close()

    def run(self) -> None:
        data_conn, cmd_conn = None, None

        try:
            # Accept connections
            data_conn, _ = self._emg_server.accept()
            logging.info("Accepted upstream connection")
            cmd_conn, _ = self._cmd_server.accept()
            logging.info("Accepted downstream connection")

            # Handshake
            cmd_conn.sendall(struct.pack("<?", True))
            cmd_conn.recv(1)
            self._state = State.RUN

            # Relay loop
            while True:
                # Read data from server socket
                data = recvall(data_conn, n_bytes=self._n_bytes)
                if data is None:
                    break

                # Convert to numpy arrays
                acc = np.frombuffer(
                    data[: self._n_ch_acc * self._win_size * 4], dtype=np.float32
                ).reshape(self._win_size, self._n_ch_acc)
                gyro = np.frombuffer(
                    data[self._n_ch_acc * self._win_size * 4 :], dtype=np.float32
                ).reshape(self._win_size, self._n_ch_gyro)

                # Convert units
                acc = acc / 1000  # mg -> g
                gyro = gyro * np.pi / 180_000  # mdps -> rad/s

                # Compute pitch and roll
                ax = acc[:, 0]
                ay = acc[:, 1]
                az = acc[:, 2]
                pitch_acc = np.atan2(-ax, np.sqrt(ay**2 + az**2))
                roll_acc = np.atan2(ay, az)

                # Refine with gyroscope
                gyro_x = gyro[:, 0]
                gyro_y = gyro[:, 1]
                dt = 1 / self._fs
                alpha = 0.98
                pitch, self._zi_pitch = signal.lfilter(
                    [1.0],
                    [1.0, -alpha],
                    alpha * dt * gyro_y + (1 - alpha) * pitch_acc,
                    axis=0,
                    zi=self._zi_pitch,
                )
                roll, self._zi_roll = signal.lfilter(
                    [1.0],
                    [1.0, -alpha],
                    alpha * dt * gyro_x + (1 - alpha) * roll_acc,
                    axis=0,
                    zi=self._zi_roll,
                )

                # Extract features
                x = np.stack([pitch, roll])
                x = np.concatenate(
                    [
                        np.mean(x, axis=-1),
                        np.std(x, axis=-1),
                        np.max(x, axis=-1),
                        np.min(x, axis=-1),
                    ]
                )

                # Classify
                pred = int(self._model.predict(x.reshape(1, -1)).squeeze())
                logging.info("Predicted label: %s", label_map.get(pred, "Unknown"))

                # Send command to PyGame
                cmd_conn.sendall(struct.pack("<Bf", int(pred), 0.4))

        except KeyboardInterrupt:
            logging.info("Manual shutdown, exiting...")
        except ConnectionError:
            logging.error("Connection terminated by client, exiting...")
        finally:
            # Clean up
            if data_conn is not None:
                data_conn.close()
            if cmd_conn is not None:
                cmd_conn.close()


def main():
    # Parse inputs
    parser = argparse.ArgumentParser(description="Fitts' Law Middleware")
    parser.add_argument(
        "--data_endpoint",
        type=str,
        required=True,
        help='Endpoint for receiving BioGUI data, either a Unix socket path or an "address:port" string for TCP.',
    )
    parser.add_argument(
        "--cmd_endpoint",
        type=str,
        required=True,
        help='Endpoint for sending commands, either a Unix socket path or an "address:port" string for TCP.',
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Whether to enable INFO level logging.",
    )
    parser.add_argument(
        "--model_path",
        type=str,
        required=True,
        help="Path to the trained SKOPS model",
    )
    args = parser.parse_args()

    if args.log:
        logging.basicConfig(level=logging.INFO)

    # Create and start relay
    server_relay = ServerRelay(
        data_endpoint=parse_endpoint(args.data_endpoint),
        cmd_endpoint=parse_endpoint(args.cmd_endpoint),
        model_path=args.model_path,
    )
    server_relay.run()


if __name__ == "__main__":
    main()
