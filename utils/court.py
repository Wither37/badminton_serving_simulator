"""球場與場地元件繪製"""
from ursina import *
from utils.config import *

class Court:
    def __init__(self):
        self.entities = []
        self._create_ground()
        self._create_play_area(x_offset=0.0, decorative=False)
        if DECORATIVE_COURTS["enabled"]:
            side_offset = COURT_W + DECORATIVE_COURTS["side_gap"]
            self._create_play_area(x_offset=-side_offset, decorative=True)
            self._create_play_area(x_offset=side_offset, decorative=True)
    
    def _create_ground(self):
        self.ground = Entity(
            model='plane', 
            collider='box', 
            scale=64, 
            texture='beautiful-wood-texture-background',
            texture_scale=(20, 20)
        )
        self.entities.append(self.ground)
    
    def _create_play_area(self, x_offset=0.0, decorative=False):
        self._create_court(x_offset=x_offset, decorative=decorative)
        self._create_net(x_offset=x_offset)
        self._draw_lines(x_offset=x_offset)
    
    def _create_court(self, x_offset=0.0, decorative=False):
        court_kwargs = {
            "model": 'quad',
            "scale": (COURT_W, COURT_LEN),
            "color": color.rgb(40/255, 110/255, 40/255),
            "rotation_x": 90,
            "position": (x_offset, 0.01, 0),
        }
        if not decorative:
            court_kwargs["collider"] = 'box'

        court = Entity(**court_kwargs)
        if not decorative:
            self.court = court
        self.entities.append(court)
    
    def _create_net(self, x_offset=0.0):
        """Create a badminton-style net with posts and visible mesh."""
        net_parts = []
        if x_offset == 0:
            self.net = net_parts

        net_drop = 1.02
        net_bottom = max(0.05, NET_H - net_drop)
        net_height = NET_H - net_bottom
        net_line_thickness = 0.014
        net_depth = 0.018
        top_tape_thickness = 0.045
        bottom_tape_thickness = 0
        mesh_color = color.rgba(35/255, 35/255, 35/255, 210/255)
        tape_color = color.rgba(245/255, 245/255, 235/255, 1)
        post_color = color.rgb(255/255, 210/255, 25/255)

        def add_net_part(scale, position, part_color):
            part = Entity(
                model='cube',
                color=part_color,
                scale=scale,
                position=position
            )
            net_parts.append(part)
            self.entities.append(part)
            return part

        # Yellow side posts just outside the doubles sidelines.
        post_height = max(1.55, NET_H + 0.05)
        post_thickness = 0.09
        post_x = HALF_W + post_thickness / 2
        for x_pos in (-post_x, post_x):
            add_net_part(
                scale=(post_thickness, post_height, post_thickness),
                position=(x_offset + x_pos, post_height / 2, NET_X),
                part_color=post_color
            )

        # Top and bottom tapes keep the mesh suspended above the floor.
        add_net_part(
            scale=(COURT_W + 0.16, top_tape_thickness, net_depth * 1.4),
            position=(x_offset, NET_H - top_tape_thickness / 2, NET_X),
            part_color=tape_color
        )
        add_net_part(
            scale=(COURT_W + 0.08, bottom_tape_thickness, net_depth),
            position=(x_offset, net_bottom + bottom_tape_thickness / 2, NET_X),
            part_color=tape_color
        )

        # Mesh lines: no transparent panel, just a visible grid.
        vertical_spacing = 0.14
        x_pos = -HALF_W
        while x_pos <= HALF_W + 0.001:
            add_net_part(
                scale=(net_line_thickness, net_height, net_depth),
                position=(x_offset + x_pos, net_bottom + net_height / 2, NET_X),
                part_color=mesh_color
            )
            x_pos += vertical_spacing

        horizontal_spacing = 0.08
        y_pos = net_bottom + horizontal_spacing
        while y_pos < NET_H - horizontal_spacing / 2:
            add_net_part(
                scale=(COURT_W, net_line_thickness, net_depth),
                position=(x_offset, y_pos, NET_X),
                part_color=mesh_color
            )
            y_pos += horizontal_spacing
    
    def _draw_lines(self, x_offset=0.0):
        """繪製所有場地線條"""
        # Baselines
        self._add_line_x_full(Z_BASELINE_NEAR, x_offset=x_offset)
        self._add_line_x_full(Z_BASELINE_FAR, x_offset=x_offset)
        
        # Sidelines
        self._add_line_z_full(-HALF_W, x_offset=x_offset)
        self._add_line_z_full(HALF_W, x_offset=x_offset)
        self._add_line_z_full(-SINGLES_HALF_W, x_offset=x_offset)
        self._add_line_z_full(SINGLES_HALF_W, x_offset=x_offset)
        
        # Service lines
        self._add_line_x_full(Z_SHORT_SERVICE_NEAR, x_offset=x_offset)
        self._add_line_x_full(Z_SHORT_SERVICE_FAR, x_offset=x_offset)
        self._add_line_x_full(Z_LONG_SERVICE_DOUBLES_NEAR, x_offset=x_offset)
        self._add_line_x_full(Z_LONG_SERVICE_DOUBLES_FAR, x_offset=x_offset)
        
        # Center lines
        self._add_line_z_segment(0, Z_SHORT_SERVICE_NEAR, Z_BASELINE_NEAR, x_offset=x_offset)
        self._add_line_z_segment(0, Z_SHORT_SERVICE_FAR, Z_BASELINE_FAR, x_offset=x_offset)
    
    def _add_line_x_full(self, z_pos, x_offset=0.0):
        line = Entity(
            model='quad', color=color.white,
            scale=(COURT_W, LINE_THICKNESS),
            position=(x_offset, LINE_Y_OFFSET, z_pos),
            rotation_x=90
        )
        self.entities.append(line)
    
    def _add_line_z_full(self, x_pos, x_offset=0.0):
        line = Entity(
            model='quad', color=color.white,
            scale=(LINE_THICKNESS, COURT_LEN),
            position=(x_offset + x_pos, LINE_Y_OFFSET, 0),
            rotation_x=90
        )
        self.entities.append(line)
    
    def _add_line_z_segment(self, x_pos, z_start, z_end, x_offset=0.0):
        length = abs(z_end - z_start)
        center_z = (z_start + z_end) / 2
        line = Entity(
            model='quad', color=color.white,
            scale=(LINE_THICKNESS, length),
            position=(x_offset + x_pos, LINE_Y_OFFSET, center_z),
            rotation_x=90
        )
        self.entities.append(line)
