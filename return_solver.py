"""回球方案計算與顯示"""
from math import atan2, degrees
from ursina import *
from physics import simulate_trajectory, find_fastest_clearing_shot
from config import *

class ReturnSolver:
    def __init__(self, ball, ui_manager, game_state):
        self.return_entities = []
        self.return_options = []
        self.colors = [color.cyan, color.lime, color.orange]
        self.return_presets = self._init_presets()
        self.ball = ball  # 儲存 ball 物件
        self.current_return_view = '0'
        self.ui = ui_manager
        self.game_state = game_state
    
    def _init_presets(self):
        presets = []
        for i in range(3):
            for j in range(3):
                presets.append({
                    "name": f"{HEIGHTS[i]}m {LOCATIONS_1[j]}-{LOCATIONS_2[i]}",
                    "height": HEIGHTS[i],
                    "target_x": TARGETS_X[i],
                    "target_y": TARGET_YS[j],
                    "color": self.colors[i],
                    "solution": None
                })
        return presets
    
    def compute_solutions(self, last_landing, current_speed, current_yaw, current_pitch):
        """計算所有回球方案"""
        if last_landing is None:
            return

        print(f"Computing return solutions for speed={current_speed} m/s, yaw={current_yaw}°, pitch={current_pitch}°")
        serve_sim = simulate_trajectory(
            speed_mps=current_speed,
            yaw_deg=current_yaw,
            pitch_deg=current_pitch,
            refine_net=True, refine_heights=True,
            refine_heights_list=HEIGHTS,
            max_t=6.0,
            start_x=0.0,
            start_y=0.0,
            start_z=RELEASE_HEIGHT,
        )
        apex_z = serve_sim['apex']['z']
        hit_points = serve_sim.get('hit_points', {})

        for preset in self.return_presets:
            if preset['solution'] is not None:
                continue

            h = preset['height']
            if h > apex_z:
                preset['solution'] = None
                continue

            hit_point = hit_points.get(h)
            if not hit_point:
                preset['solution'] = None
                continue

            delta_x = preset['target_x'] - hit_point['x']
            delta_y = preset['target_y'] - hit_point['y']
            yaw_deg = degrees(atan2(delta_y, delta_x))

            speed, pitch, sim = find_fastest_clearing_shot(
                start_x=hit_point['x'],
                target_x=preset['target_x'],
                start_z=h,
                yaw_deg=yaw_deg,
                start_y=hit_point['y']
            )
            if speed:
                solution = {'speed': speed, 'pitch': pitch, 'sim': sim, 'hit_point': hit_point, 'yaw_deg': yaw_deg}
                preset['solution'] = solution
            else:
                preset['solution'] = None
    
    def display_view(self, view_id, last_landing):
        """顯示回球方案"""
        self.clear_entities()
        self.current_return_view = view_id
        self.return_options = []

        if last_landing is None:
            self.ui.update_return_info("No landing yet.")
            return

        target_preset = None
        if view_id == '0':
            self.ui.update_return_info("Showing ALL return options")
        else:
            idx = int(view_id) - 1
            if 0 <= idx < len(self.return_presets):
                target_preset = self.return_presets[idx]
                self.ui.update_return_info(f"Return {idx+1}: {target_preset['name']}\n" \
                                    f"{'No solution' if not target_preset['solution'] else ''}")
            else:
                self.ui.update_return_info("Invalid return ID")
                return

        if view_id == '0':
            # Draw static trails for all
            for e in self.game_state.return_trails:
                destroy(e)
            self.game_state.return_trails.clear()
            
            for i, preset in enumerate(self.return_presets):
                sol = preset['solution']
                if not sol:
                    continue

                sim = sol['sim']
                land = sim['landing']
                if not land:
                    continue

                # Trail
                trail_color = color.rgba(preset['color'].r, preset['color'].g, preset['color'].b, 0.6)
                for p in sim['points']:
                    trail = Entity(model='sphere', scale=0.02, color=trail_color,
                                position=(p[1], p[2], p[0]))
                    self.return_entities.append(trail)

                # Landing marker
                marker = Entity(model='sphere', scale=0.15, color=preset['color'],
                                position=(land['y'], 0.05, land['x']))
                self.return_entities.append(marker)

                # Label
                label = Text(text=str(i+1), scale=2,
                            position=(0, 0.2, 0), parent=marker, billboard=True)
                self.return_entities.append(label)

                self.return_options.append((i, preset))
        else:
            # Animate single return
            if target_preset:
                sol = target_preset['solution']
                if sol:
                    hit_point = sol['hit_point']
                    h = target_preset['height']
                    speed = sol['speed']
                    yaw_deg = sol['yaw_deg']
                    pitch = sol['pitch']
                    
                    for e in self.game_state.return_trails:
                        destroy(e)
                    self.game_state.return_trails.clear()
                    
                    sim = simulate_trajectory(speed, yaw_deg, pitch, start_x=hit_point['x'], start_y=hit_point['y'], start_z=h)
                    self.game_state.trajectory_points = sim['points']
                    self.game_state.simulation_time = 0.0
                    self.game_state.trail_timer = 0.0
                    self.game_state.simulation_type = 'return'
                    self.ball.position = (hit_point['y'], h, hit_point['x'])
                    self.ball.color = target_preset['color']
    
    def clear_entities(self):
        """清除回球顯示"""
        for e in self.return_entities:
            destroy(e)
        self.return_entities.clear()
        self.ui.hide_return_info()