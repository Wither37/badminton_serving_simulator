"""回球方案計算與顯示"""
from math import atan2, degrees
from ursina import *
from utils.physics import simulate_trajectory, find_fastest_clearing_shot
from utils.config import *

class ReturnSolver:
    def __init__(self, ball, ui_manager, game_state):
        self.return_entities = []
        self.colors = [color.cyan, color.lime, color.orange]
        self.preset_template = self._init_presets()
        self.ball = ball  # 儲存 ball 物件
        self.current_return_view = '0'
        self.ui = ui_manager
        self.game_state = game_state
        self._animation_active = False
        self._animation_points = []
        self._animation_time = 0.0
        self._animation_trail_timer = 0.0
        self._animation_trail_interval = TRAIL_INTERVAL
        self._animation_color = color.white
    
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

    def _new_presets_for_ball(self):
        return [dict(preset, solution=None) for preset in self.preset_template]
    
    def compute_solutions(self, ball_obj):
        """為單一球物件計算並儲存回球方案"""
        if ball_obj is None or getattr(ball_obj, 'landing', None) is None:
            return

        if getattr(ball_obj, 'return_solutions_ready', False):
            return

        ball_obj.return_presets = self._new_presets_for_ball()

        print(f"Computing return solutions for speed={ball_obj.speed} m/s, yaw={ball_obj.yaw}°, pitch={ball_obj.pitch}°")
        serve_sim = getattr(ball_obj, 'serve_sim', None)
        if not serve_sim or 'hit_points' not in serve_sim:
            serve_sim = simulate_trajectory(
                speed_mps=ball_obj.speed,
                yaw_deg=ball_obj.yaw,
                pitch_deg=ball_obj.pitch,
                refine_net=True, refine_heights=True,
                refine_heights_list=HEIGHTS,
                max_t=6.0,
                start_x=ball_obj.start_x,
                start_y=ball_obj.start_y,
                start_z=ball_obj.start_z,
            )
        apex_z = serve_sim['apex']['z']
        hit_points = serve_sim.get('hit_points', {})

        for preset in ball_obj.return_presets:
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
            if speed is not None:
                solution = {'speed': speed, 'pitch': pitch, 'sim': sim, 'hit_point': hit_point, 'yaw_deg': yaw_deg}
                preset['solution'] = solution
            else:
                preset['solution'] = None

        ball_obj.return_solutions_ready = True
    
    def display_view(self, view_id, ball_obj):
        """顯示回球方案"""
        self.clear_entities()
        self.ball.visible = True
        self.current_return_view = view_id

        if ball_obj is None or not getattr(ball_obj, 'return_solutions_ready', False):
            self.ui.update_return_info("No landing yet.")
            return

        return_presets = getattr(ball_obj, 'return_presets', [])
        if not return_presets:
            self.ui.update_return_info("No return options.")
            return

        target_preset = None
        if view_id == '0':
            self.ui.update_return_info("Showing ALL return options")
        else:
            idx = int(view_id) - 1
            if 0 <= idx < len(return_presets):
                target_preset = return_presets[idx]
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
            
            for i, preset in enumerate(return_presets):
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
        else:
            # Animate single return
            if target_preset:
                sol = target_preset['solution']
                if sol:
                    hit_point = sol['hit_point']
                    sim = sol['sim']
                    h = target_preset['height']
                    
                    for e in self.game_state.return_trails:
                        destroy(e)
                    self.game_state.return_trails.clear()

                    self.ball.position = (hit_point['y'], h, hit_point['x'])
                    self.ball.color = target_preset['color']
                    self._start_return_animation(sim['points'], target_preset['color'])

    def _start_return_animation(self, points, ball_color):
        if not points:
            return

        self._animation_points = points
        self._animation_time = 0.0
        self._animation_trail_timer = 0.0
        self._animation_color = ball_color
        self._animation_active = True

    def is_animating(self):
        return self._animation_active

    def stop_animation(self):
        self._animation_active = False
        self._animation_points = []

    def update_animation(self):
        """每幀更新單一回球動畫（與發球同樣的時間插值邏輯）。"""
        if not self._animation_active or not self._animation_points:
            return

        self._animation_time += time.dt
        points = self._animation_points

        for i in range(len(points) - 1):
            curr_t = points[i][6]
            next_t = points[i + 1][6]

            if curr_t <= self._animation_time < next_t:
                frac = (self._animation_time - curr_t) / (next_t - curr_t)
                curr_pos = points[i]
                next_pos = points[i + 1]

                x = curr_pos[0] + frac * (next_pos[0] - curr_pos[0])
                y = curr_pos[1] + frac * (next_pos[1] - curr_pos[1])
                z = curr_pos[2] + frac * (next_pos[2] - curr_pos[2])
                self.ball.position = (y, z, x)

                self._animation_trail_timer += time.dt
                if self._animation_trail_timer >= self._animation_trail_interval:
                    trail = Entity(model='sphere', scale=0.03, color=self._animation_color, position=self.ball.position)
                    self.game_state.return_trails.append(trail)
                    self._animation_trail_timer -= self._animation_trail_interval
                return

        final_pos = points[-1]
        self.ball.position = (final_pos[1], final_pos[2], final_pos[0])
        self.stop_animation()
    
    def clear_entities(self):
        """清除回球顯示"""
        self.stop_animation()

        for e in self.game_state.return_trails:
            destroy(e)
        self.game_state.return_trails.clear()

        for e in self.return_entities:
            destroy(e)
        self.return_entities.clear()
        self.ui.hide_return_info()
        self.ball.visible = False