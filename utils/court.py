"""球場與場地元件繪製"""
from ursina import *
from utils.config import *

class Court:
    def __init__(self):
        self.entities = []
        self._create_ground()
        self._create_court()
        self._create_net()
        self._draw_lines()
    
    def _create_ground(self):
        self.ground = Entity(
            model='plane', 
            collider='box', 
            scale=64, 
            texture='grass', 
            texture_scale=(4,4)
        )
        self.entities.append(self.ground)
    
    def _create_court(self):
        self.court = Entity(
            model='quad', 
            scale=(COURT_W, COURT_LEN),
            color=color.rgb(40/255, 110/255, 40/255),
            rotation_x=90,
            position=(0, 0.01, 0),
            collider='box'
        )
        self.entities.append(self.court)
    
    def _create_net(self):
        """Create a badminton-style net with posts and visible mesh."""
        self.net = []

        net_drop = 1.02
        net_bottom = max(0.05, NET_H - net_drop)
        net_height = NET_H - net_bottom
        net_line_thickness = 0.014
        net_depth = 0.018
        top_tape_thickness = 0.045
        bottom_tape_thickness = 0.035
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
            self.net.append(part)
            self.entities.append(part)
            return part

        # Yellow side posts just outside the doubles sidelines.
        post_height = max(1.55, NET_H + 0.05)
        post_thickness = 0.09
        post_x = HALF_W + post_thickness / 2
        for x_pos in (-post_x, post_x):
            add_net_part(
                scale=(post_thickness, post_height, post_thickness),
                position=(x_pos, post_height / 2, NET_X),
                part_color=post_color
            )

        # Top and bottom tapes keep the mesh suspended above the floor.
        add_net_part(
            scale=(COURT_W + 0.16, top_tape_thickness, net_depth * 1.4),
            position=(0, NET_H - top_tape_thickness / 2, NET_X),
            part_color=tape_color
        )
        add_net_part(
            scale=(COURT_W + 0.08, bottom_tape_thickness, net_depth),
            position=(0, net_bottom + bottom_tape_thickness / 2, NET_X),
            part_color=tape_color
        )

        # Mesh lines: no transparent panel, just a visible grid.
        vertical_spacing = 0.14
        x_pos = -HALF_W
        while x_pos <= HALF_W + 0.001:
            add_net_part(
                scale=(net_line_thickness, net_height, net_depth),
                position=(x_pos, net_bottom + net_height / 2, NET_X),
                part_color=mesh_color
            )
            x_pos += vertical_spacing

        horizontal_spacing = 0.08
        y_pos = net_bottom + horizontal_spacing
        while y_pos < NET_H - horizontal_spacing / 2:
            add_net_part(
                scale=(COURT_W, net_line_thickness, net_depth),
                position=(0, y_pos, NET_X),
                part_color=mesh_color
            )
            y_pos += horizontal_spacing
    
    def _draw_lines(self):
        """繪製所有場地線條"""
        # Baselines
        self._add_line_x_full(Z_BASELINE_NEAR)
        self._add_line_x_full(Z_BASELINE_FAR)
        
        # Sidelines
        self._add_line_z_full(-HALF_W)
        self._add_line_z_full(HALF_W)
        self._add_line_z_full(-SINGLES_HALF_W)
        self._add_line_z_full(SINGLES_HALF_W)
        
        # Service lines
        self._add_line_x_full(Z_SHORT_SERVICE_NEAR)
        self._add_line_x_full(Z_SHORT_SERVICE_FAR)
        self._add_line_x_full(Z_LONG_SERVICE_DOUBLES_NEAR)
        self._add_line_x_full(Z_LONG_SERVICE_DOUBLES_FAR)
        
        # Center lines
        self._add_line_z_segment(0, Z_SHORT_SERVICE_NEAR, Z_BASELINE_NEAR)
        self._add_line_z_segment(0, Z_SHORT_SERVICE_FAR, Z_BASELINE_FAR)
    
    def _add_line_x_full(self, z_pos):
        line = Entity(
            model='quad', color=color.white,
            scale=(COURT_W, LINE_THICKNESS),
            position=(0, LINE_Y_OFFSET, z_pos),
            rotation_x=90
        )
        self.entities.append(line)
    
    def _add_line_z_full(self, x_pos):
        line = Entity(
            model='quad', color=color.white,
            scale=(LINE_THICKNESS, COURT_LEN),
            position=(x_pos, LINE_Y_OFFSET, 0),
            rotation_x=90
        )
        self.entities.append(line)
    
    def _add_line_z_segment(self, x_pos, z_start, z_end):
        length = abs(z_end - z_start)
        center_z = (z_start + z_end) / 2
        line = Entity(
            model='quad', color=color.white,
            scale=(LINE_THICKNESS, length),
            position=(x_pos, LINE_Y_OFFSET, center_z),
            rotation_x=90
        )
        self.entities.append(line)
