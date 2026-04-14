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
            position=(0, 0.01, COURT_LEN / 2),
            collider='box'
        )
        self.entities.append(self.court)
    
    def _create_net(self):
        self.net = Entity(
            model='quad', 
            color=color.rgba(100/255, 100/255, 100/255, 150/255),
            scale=(COURT_W, NET_H),
            position=(0, NET_H / 2, NET_X),
            double_sided=True
        )
        self.entities.append(self.net)
    
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
            position=(x_pos, LINE_Y_OFFSET, COURT_LEN / 2),
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