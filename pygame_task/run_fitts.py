# Copyright University of Bologna - ETH Zurich 2026
# Licensed under Apache v2.0 see LICENSE for details.
#
# SPDX-License-Identifier: Apache-2.0

"""
This module runs a Fitts' Law task in PyGame.


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
import math
import os
import socket
import struct
import time
from enum import Enum, IntEnum
from sys import platform

import numpy as np
import pygame

# Colors
BLACK = (0, 0, 0)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
BLUE = (0, 102, 204)


type Endpoint = str | tuple[str, int]


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


class Direction(IntEnum):
    """Movement direction."""

    REST = 0
    RIGHT = 1
    LEFT = 2
    UP = 3
    DOWN = 4


class FittsTask:
    """
    Fitts' style task.

    Parameters
    ----------
    endpoint : Endpoint
        Endpoint for the command service, either a Unix socket path or an
        address:port pair for TCP.
    n_trials : int or None, default=None
        Number of trials to perform. If None, run until max_time is reached.
    max_time : float or None, default=None
        Maximum time (in seconds) for the task. If None, no time limit is applied.
    dwell_time : float, default=1.0
        Dwell time (in seconds) required to select a target.
    fps : float, default=20
        Frames per second.
    width : int, default=720
        Width of the PyGame window.
    height : int, default=720
        Height of the PyGame window.
    """

    def __init__(
        self,
        endpoint: Endpoint,
        n_trials: int | None = None,
        max_time: float | None = None,
        dwell_time: float = 1.0,
        fps: float = 60,
        width: int = 720,
        height: int = 720,
    ):
        assert (
            n_trials is not None or max_time is not None
        ), "Either n_trials or max_time must be specified."

        # If running in Linux, set SDL to use the X11 video driver
        if platform == "linux" or platform == "linux2":
            os.environ["SDL_VIDEODRIVER"] = "x11"

        # PyGame configuration
        pygame.init()
        pygame.display.set_caption("Fitts's Law Task")
        self._width = width
        self._height = height
        self._font = pygame.font.SysFont("helvetica", 40)
        self._screen = pygame.display.set_mode([self._width, self._height])
        self._clock = pygame.time.Clock()
        self._fps = fps
        self._quit = False

        # Cursor
        self._cursor_size = 14
        self._cursor = pygame.Rect(
            self._width // 2 - self._cursor_size // 2,
            self._height // 2 - self._cursor_size // 2,
            self._cursor_size,
            self._cursor_size,
        )
        self._cur_dir = [0, 0]
        self._max_speed = 25

        # Target circles
        self._radius_small = 40
        self._circles = []
        self._target_circle = -1
        self._next_target()
        self._dwell_time = dwell_time
        self._dwell_timer = None
        self._trial = 0
        self._n_trials = n_trials

        # Socket for incoming commands
        self._endpoint = endpoint
        self._cmd_sock = None
        self._connect_interval = 5.0  # seconds
        self._rx_buffer = b""

        # Track time
        self._max_time = max_time
        self._time_checkpoint = time.perf_counter()

        # State
        self._state = State.CONNECT

    def run(self):
        while not self._quit:
            self._draw()

            match self._state:
                case State.CONNECT:
                    self._dim_background()
                    self._blit_center(
                        "Waiting to connect...", y_offset=-10, font_size=48
                    )
                    self._blit_center(
                        "Start middleware and BioGUI.", y_offset=30, font_size=36
                    )
                    self._wait_for_connection()
                case State.RUN:
                    try:
                        # Read command (non-blocking)
                        self._read_cmd()
                        self._move()
                    except BlockingIOError:
                        pass

                    self._check_collisions()

                    if self._max_time is not None:
                        now = time.perf_counter()
                        if now - self._time_checkpoint > self._max_time:
                            self._quit = True
                case _:
                    raise ValueError(f"Invalid state: {self._state}")

            # Update scene
            pygame.display.update()
            self._clock.tick(self._fps)

            # Detect close event
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._quit = True

        pygame.quit()

    def _wait_for_connection(self):
        # Connect
        if self._cmd_sock is None:
            now = time.perf_counter()
            if now - self._time_checkpoint < self._connect_interval:
                return

            match self._endpoint:
                case str():
                    if platform == "win32":
                        raise RuntimeError("Unix sockets are not supported on Windows.")
                    cmd_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                case (str(), int()):
                    cmd_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                case _:
                    raise ValueError("Invalid endpoint type.")

            self._time_checkpoint = now
            try:
                cmd_sock.connect(self._endpoint)
            except (ConnectionRefusedError, FileNotFoundError):
                cmd_sock.close()
                logging.info("Waiting to connect to %s...", self._endpoint)
                return

            self._cmd_sock = cmd_sock

            # Disable Nagle's algorithm to send small packets immediately
            try:
                self._cmd_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                logging.warning("Failed to set TCP_NODELAY on socket.")

            self._cmd_sock.setblocking(False)
            logging.info("Connected to socket.")

        # Handshake
        if self._cmd_sock is not None:
            try:
                self._cmd_sock.recv(1)
                self._cmd_sock.sendall(struct.pack("<?", True))
            except BlockingIOError:
                return

        logging.info("Handshake completed.")
        self._state = State.RUN
        self._time_checkpoint = time.perf_counter()

    def _dim_background(self, alpha=200):
        veil = pygame.Surface(self._screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, alpha))
        self._screen.blit(veil, (0, 0))

    def _blit_center(self, text, y_offset=0, font_size=36):
        font = pygame.font.SysFont(None, font_size)
        surf = font.render(text, True, (240, 240, 240))
        rect = surf.get_rect(
            center=(
                self._screen.get_width() // 2,
                self._screen.get_height() // 2 + y_offset,
            )
        )
        self._screen.blit(surf, rect)

    def _draw(self):
        self._screen.fill(BLACK)

        # 1. Target circle
        if self._target_circle != -1:
            target_circle = self._circles[self._target_circle]
            pygame.draw.circle(
                self._screen,
                RED,
                (target_circle.centerx, target_circle.centery),
                target_circle[2] // 2,
            )

        # 2. Cursor
        pygame.draw.circle(
            self._screen,
            YELLOW,
            (
                self._cursor.x + self._cursor_size // 2,
                self._cursor.y + self._cursor_size // 2,
            ),
            self._cursor_size // 2,
        )

        # 3. Timer
        if self._dwell_timer is not None:
            toc = time.perf_counter()
            duration = round((toc - self._dwell_timer), 2)
            time_str = str(duration)
            draw_text = self._font.render(time_str, True, BLUE)
            self._screen.blit(draw_text, (10, 10))

    def _read_cmd(self) -> None:
        assert self._cmd_sock is not None, "Command socket is not initialized."

        try:
            chunk = self._cmd_sock.recv(5)
            if not chunk:
                # Socket closed by peer
                self._cur_dir = [0, 0]
                return
            self._rx_buffer += chunk
        except BlockingIOError:
            pass

        if len(self._rx_buffer) < 5:
            # Not enough bytes yet for a full prediction frame.
            self._cur_dir = [0, 0]
            return

        # Consume exactly one complete 5-byte frame (oldest first), leaving
        # any extra buffered bytes for the next call.
        frame, self._rx_buffer = self._rx_buffer[:5], self._rx_buffer[5:]

        try:
            label, vel = struct.unpack("<Bf", frame)
            label = Direction(label)
            vel = int(round(vel * self._max_speed))
        except (struct.error, ValueError) as e:
            logging.warning("Dropped malformed command frame %r: %s", frame, e)
            self._cur_dir = [0, 0]
            return

        match label:
            case Direction.LEFT:
                self._cur_dir = [-vel, 0]
            case Direction.UP:
                self._cur_dir = [0, -vel]
            case Direction.DOWN:
                self._cur_dir = [0, vel]
            case Direction.RIGHT:
                self._cur_dir = [vel, 0]
            case Direction.REST:
                self._cur_dir = [0, 0]
            case _:
                raise ValueError(f"Invalid label received: {label}")

    def _move(self):
        self._cursor.x = min(
            self._width - self._cursor_size,
            max(0, self._cursor.x + self._cur_dir[0]),
        )
        self._cursor.y = min(
            self._height - self._cursor_size,
            max(0, self._cursor.y + self._cur_dir[1]),
        )

    def _check_collisions(self):
        target = self._circles[self._target_circle]
        if (
            math.sqrt(
                (target.centerx - self._cursor.centerx) ** 2
                + (target.centery - self._cursor.centery) ** 2
            )
            <= target[2] / 2
        ):
            if self._dwell_timer is None:
                self._dwell_timer = time.perf_counter()
                duration = 0
            else:
                toc = time.perf_counter()
                duration = round((toc - self._dwell_timer), 2)
            if duration >= self._dwell_time:
                self._next_target()
                self._dwell_timer = None
                if self._n_trials is not None and self._trial >= self._n_trials - 1:
                    self._quit = True
                else:
                    self._trial += 1
        else:
            self._dwell_timer = None

    def _next_target(self):
        while True:
            target_radius = np.random.randint(self._cursor[2] * 2, self._radius_small)
            target_position = np.random.randint(
                target_radius, min(self._width, self._height) // 2 - target_radius
            )
            target_angle = np.random.uniform(0, 2 * math.pi)
            target_x = self._width // 2 + target_position * math.cos(target_angle)
            target_y = self._height // 2 + target_position * math.sin(target_angle)
            if (
                math.dist((target_x, target_y), self._cursor.center)
                > target_radius + self._cursor[2] // 2
            ):
                break

        self._circles = [
            pygame.Rect(
                int(target_x - target_radius),
                int(target_y - target_radius),
                target_radius * 2,
                target_radius * 2,
            )
        ]
        self._target_circle = 0

    def __del__(self):
        if self._cmd_sock is not None:
            self._cmd_sock.close()


def main():
    # Parse inputs
    parser = argparse.ArgumentParser(description="Fitts PyGame Interface")
    parser.add_argument(
        "--n_trials",
        type=int,
        required=False,
        default=None,
        help="Number of trials",
    )
    parser.add_argument(
        "--fps",
        type=float,
        required=False,
        default=30,
        help="Frames per second (controls polling frequency)",
    )
    parser.add_argument(
        "--max_time",
        type=float,
        required=False,
        default=None,
        help="Maximum time for the task (in seconds)",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        required=True,
        help='Endpoint for the command service, either a Unix socket path or an "address:port" string for TCP.',
    )
    args = parser.parse_args()

    # Start Fitts' task
    ifl = FittsTask(
        endpoint=parse_endpoint(args.endpoint),
        n_trials=args.n_trials,
        max_time=args.max_time,
        fps=args.fps,
        dwell_time=1.5,
    )
    try:
        ifl.run()
    except KeyboardInterrupt:
        logging.info("Manual shutdown, exiting...")
    except Exception:
        logging.error("Connection terminated by server, exiting...")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    main()
