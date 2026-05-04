from ursina import *
from utils.physics import simulate_trajectory
from utils.config import *

class BallFlight:
    def __init__(self, speed_mps, yaw_deg, pitch_deg, ui, simulator, state, interval, start_x=0.0, start_y=0.0, start_z=RELEASE_HEIGHT):
        self.speed = speed_mps
        self.yaw = yaw_deg
        self.pitch = pitch_deg
        self.interval = interval
        self.ui = ui
        self.simulator = simulator
        self.state = state
        self.start_x = start_x
        self.start_y = start_y
        self.start_z = start_z
        self.landing = None

        sim = simulate_trajectory(
            speed_mps, yaw_deg, pitch_deg,
            start_x=start_x, start_y=start_y, start_z=start_z
        )
        self.points = sim["points"]
        self.simulation_time = 0.0
        self.trail_timer = 0.0
        self.finished = False
        self.trail_clear_timer = None
        self.hide_after_return_contact = False

        self.entity = Entity(
            model='sphere',
            position=(start_y, start_z, start_x),
            color=color.yellow,
            scale=0.25
        )

        self.trail_entities = []

    def update(self):
        if self.finished:
            if self.trail_clear_timer is not None:
                self.trail_clear_timer = max(0.0, self.trail_clear_timer - time.dt)
                if self.trail_clear_timer <= 0.0:
                    for e in self.trail_entities:
                        destroy(e)
                    self.trail_entities.clear()
                    self.trail_clear_timer = None
            return

        self.simulation_time += time.dt

        for i in range(len(self.points) - 1):
            curr_t = self.points[i][6]
            next_t = self.points[i + 1][6]

            if curr_t <= self.simulation_time < next_t:
                frac = (self.simulation_time - curr_t) / (next_t - curr_t)

                curr_pos = self.points[i]
                next_pos = self.points[i + 1]

                x = curr_pos[0] + frac * (next_pos[0] - curr_pos[0])
                y = curr_pos[1] + frac * (next_pos[1] - curr_pos[1])
                z = curr_pos[2] + frac * (next_pos[2] - curr_pos[2])

                # Ursina: (y, z, x)
                self.entity.position = (y, z, x)
                self._update_trail()
                return

        # 超過最後一點，表示落地
        final_pos = self.points[-1]
        self.entity.position = (final_pos[1], final_pos[2], final_pos[0])
        self.land()

    def _update_trail(self):
        if self.hide_after_return_contact:
            return
        if not self.state.show_trajectory:
            return

        self.trail_timer += time.dt
        if self.trail_timer >= TRAIL_INTERVAL:
            trail = Entity(
                model='sphere',
                color=color.yellow,
                scale=0.1,
                position=self.entity.position
            )
            self.trail_entities.append(trail)
            self.trail_timer -= TRAIL_INTERVAL

    def hide_remaining_after_return_contact(self):
        self.hide_after_return_contact = True
        self.entity.visible = False

    def land(self):
        self.entity.color = color.red
        print(f"Landed at (x={self.entity.z:.2f}, y={self.entity.x:.2f})")

        self.landing = {'x': self.entity.z, 'y': self.entity.x}
        self.state.latest_landed_ball = self

        if not (SERVE_VISUAL["hide_after_return_contact"] and self.hide_after_return_contact):
            marker = Entity(
                model='sphere',
                scale=0.1,
                color=color.blue,
                position=(self.entity.x, 0.05, self.entity.z)
            )
            self.state.landing_markers.append(marker)

        self.ui.landings.append({
            'pos': (self.entity.z, self.entity.x),
            'params': (self.speed, self.yaw, self.pitch)
        })
        self.ui.update_landing_text()

        self.simulator.client.publish(self.simulator.status_topic, "serve=done")

        self.finished = True
        self.trail_clear_timer = SERVE_VISUAL["trail_clear_delay"]

    def destroy(self):
        for e in self.trail_entities:
            destroy(e)
        destroy(self.entity)
