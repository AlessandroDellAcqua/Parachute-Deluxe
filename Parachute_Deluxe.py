"""
PARACHUTE DELUXE
================
A complete rewrite of the original "Parachute" pygame project.

- 5 levels with increasing difficulty (more obstacles, wind, bird flocks)
- Random obstacle spawning (no more hard-coded "long rectangle" level)
- Lives system with invincibility blink after a hit
- Score: survival points, near-miss bonuses, level bonuses, perfect landing
- Wind gusts that push you around (with on-screen indicator)
- Pixel-perfect collisions (pygame masks, not big rectangles)
- Final landing phase on the island: hit the X for a PERFECT LANDING bonus
- Sky color changes as you descend, parallax cloud layers
- Pause (P), Restart (R), Menu start (S)

Put this file in the SAME FOLDER as the PNG assets
(PARACHUTE_BOY.PNG, ELICOPTER1-3.PNG, Uccello*.PNG, RUccello*.png,
 NUVOLA2.PNG, ISOLA.PNG, START.PNG, GAMEOVER.png, YOU_WIN.png)
then run:  python Parachute_Deluxe.py
"""

import os
import random
import math
import pygame

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
SCREEN_W, SCREEN_H = 600, 800
FPS = 60
ASSET_DIR = os.path.dirname(os.path.abspath(__file__))
# Images live in ./media ; fall back to the script folder just in case
MEDIA_DIRS = [os.path.join(ASSET_DIR, "media"), ASSET_DIR]
AUTOTEST = bool(os.environ.get("PARACHUTE_AUTOTEST"))  # headless smoke test

# Game states
MENU, PLAYING, LEVEL_CLEAR, LANDING, GAME_OVER, WIN, PAUSED = range(7)

# ----------------------------------------------------------------------------
# Level definitions  (this is where you tune the game!)
# ----------------------------------------------------------------------------
# altitude  : meters to survive before the level is cleared
# fall      : world scroll speed (px/s) -> how fast everything rushes up
# heli_rate : average seconds between helicopter spawns
# bird_rate : average seconds between bird spawns
# flock     : chance (0..1) that a bird spawn is actually a flock of 3
# wind      : max gust strength (0 = no wind)
# sky       : (top color, bottom color) of the gradient for this level
LEVELS = [
    dict(name="ALTA QUOTA",      altitude=2000, fall=150, heli_rate=2.8, bird_rate=99,  flock=0.0,  wind=0,
         sky=((20, 24, 82),   (90, 140, 220))),
    dict(name="TRAFFICO AEREO",  altitude=2200, fall=170, heli_rate=1.9, bird_rate=4.0, flock=0.0,  wind=0,
         sky=((40, 60, 140),  (120, 170, 230))),
    dict(name="VENTO FORTE",     altitude=2400, fall=190, heli_rate=2.0, bird_rate=2.6, flock=0.15, wind=120,
         sky=((70, 110, 180), (150, 200, 240))),
    dict(name="STORMO!",         altitude=2600, fall=215, heli_rate=1.7, bird_rate=1.6, flock=0.45, wind=150,
         sky=((100, 150, 210),(170, 215, 245))),
    dict(name="ATTERRAGGIO",     altitude=2800, fall=240, heli_rate=1.5, bird_rate=1.5, flock=0.35, wind=170,
         sky=((130, 180, 230),(190, 230, 250))),
]


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def load_image(*names, size=None, fallback=(255, 0, 255)):
    """Try several filenames (case differences!), fall back to a colored box."""
    for name in names:
        for folder in MEDIA_DIRS:
            path = os.path.join(folder, name)
            if not os.path.exists(path):
                continue
            img = pygame.image.load(path).convert_alpha()
            # Many of the original PNGs have an opaque black background
            # instead of real transparency -> turn black into transparent.
            corner = img.get_at((0, 0))
            if corner[3] == 255 and corner[0] < 12 and corner[1] < 12 and corner[2] < 12:
                keyed = img.convert()
                keyed.set_colorkey((corner[0], corner[1], corner[2]))
                img = pygame.Surface(keyed.get_size(), pygame.SRCALPHA)
                img.blit(keyed, (0, 0))
            if size:
                img = pygame.transform.smoothscale(img, size)
            return img
    surf = pygame.Surface(size or (60, 60), pygame.SRCALPHA)
    surf.fill((*fallback, 255))
    return surf


def make_gradient(top, bottom):
    """Pre-render a vertical sky gradient surface (cheap to blit each frame)."""
    surf = pygame.Surface((SCREEN_W, SCREEN_H))
    for y in range(SCREEN_H):
        t = y / SCREEN_H
        c = [int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)]
        pygame.draw.line(surf, c, (0, y), (SCREEN_W, y))
    return surf


def draw_heart(surface, x, y, size=18, color=(220, 40, 60)):
    r = size // 4
    pygame.draw.circle(surface, color, (x + r, y + r), r)
    pygame.draw.circle(surface, color, (x + 3 * r, y + r), r)
    pygame.draw.polygon(surface, color,
                        [(x, y + r), (x + size, y + r), (x + size // 2, y + size)])


# ----------------------------------------------------------------------------
# Entities
# ----------------------------------------------------------------------------
class FloatingText:
    """Little '+25' style popups."""
    def __init__(self, text, x, y, color=(255, 255, 80)):
        self.text, self.x, self.y, self.color = text, x, y, color
        self.life = 1.2

    def update(self, dt):
        self.y -= 40 * dt
        self.life -= dt

    def draw(self, surface, font):
        if self.life > 0:
            alpha = max(0, min(255, int(255 * self.life / 1.2)))
            img = font.render(self.text, True, self.color)
            img.set_alpha(alpha)
            surface.blit(img, (self.x, self.y))


class Player:
    def __init__(self, image):
        self.image = image
        self.mask = pygame.mask.from_surface(image)
        self.w, self.h = image.get_size()
        self.x = SCREEN_W / 2 - self.w / 2
        self.y = 140.0
        self.vx = 0.0
        self.invincible = 0.0

    def update(self, dt, keys, wind):
        accel = 900.0
        max_v = 360.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.vx -= accel * dt
        elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.vx += accel * dt
        else:
            # air friction when no key pressed
            self.vx -= self.vx * min(1.0, 4.0 * dt)
        self.vx = max(-max_v, min(max_v, self.vx))
        self.x += (self.vx + wind) * dt

        # PacMan wrap (kept from the original game!)
        if self.x > SCREEN_W:
            self.x = -self.w
        elif self.x < -self.w:
            self.x = SCREEN_W

        if self.invincible > 0:
            self.invincible -= dt

    def draw(self, surface):
        # blink while invincible
        if self.invincible > 0 and int(self.invincible * 10) % 2 == 0:
            return
        surface.blit(self.image, (self.x, self.y))

    @property
    def center_x(self):
        return self.x + self.w / 2


class Obstacle:
    def __init__(self, image, x, y, vx, kind):
        self.image = image
        self.mask = pygame.mask.from_surface(image)
        self.w, self.h = image.get_size()
        self.x, self.y, self.vx = float(x), float(y), float(vx)
        self.kind = kind            # 'heli' or 'bird'
        self.near_missed = False
        self.dead = False

    def update(self, dt, scroll):
        self.y -= scroll * dt
        self.x += self.vx * dt
        # horizontal wrap with margin
        if self.vx > 0 and self.x > SCREEN_W + 40:
            self.x = -self.w - 40
        elif self.vx < 0 and self.x < -self.w - 40:
            self.x = SCREEN_W + 40
        if self.y < -self.h - 60:
            self.dead = True

    def draw(self, surface):
        surface.blit(self.image, (self.x, self.y))

    def rect(self):
        return pygame.Rect(self.x, self.y, self.w, self.h)

    def collides(self, player):
        offset = (int(self.x - player.x), int(self.y - player.y))
        return player.mask.overlap(self.mask, offset) is not None


class Cloud:
    def __init__(self, image):
        w = random.randint(70, 150)
        self.image = pygame.transform.smoothscale(image, (w, int(w * 0.55)))
        self.x = random.randint(-40, SCREEN_W)
        self.y = random.randint(0, SCREEN_H)
        self.speedmul = random.uniform(1.2, 1.8)

    def update(self, dt, scroll):
        self.y -= scroll * self.speedmul * dt
        if self.y < -90:
            self.y = SCREEN_H + random.randint(20, 300)
            self.x = random.randint(-40, SCREEN_W)

    def draw(self, surface):
        surface.blit(self.image, (self.x, self.y))


# ----------------------------------------------------------------------------
# Main game
# ----------------------------------------------------------------------------
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Parachute Deluxe")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.big_font = pygame.font.SysFont("arial", 48, bold=True)
        self.small_font = pygame.font.SysFont("arial", 16)

        self.load_assets()
        self.gradients = [make_gradient(*lv["sky"]) for lv in LEVELS]
        self.menu_gradient = make_gradient((8, 10, 40), (60, 90, 160))
        self.menu_time = 0.0
        self.menu_clouds = [Cloud(self.img_cloud) for _ in range(7)]
        for c in self.menu_clouds:
            c.drift = random.uniform(8, 25) * random.choice((-1, 1))
        self.menu_birds = []
        self.menu_bird_timer = 1.0
        self.show_hitboxes = False
        self.reset(full=True)

    # ----------------------------------------------------------- assets
    def load_assets(self):
        self.img_player = load_image("PARACHUTE_BOY.PNG", size=(110, 110))
        self.img_helis = [
            load_image("ELICOPTER1.PNG", size=(220, 220)),
            load_image("ELICOPTER2.PNG", size=(220, 220)),
            load_image("ELICOPTER3.PNG", size=(220, 220)),
        ]
        # helicopters are drawn facing LEFT in the PNGs
        self.img_helis_flipped = [pygame.transform.flip(i, True, False) for i in self.img_helis]
        # left-facing birds
        self.img_birds_left = [
            load_image("Uccello1.PNG", size=(70, 70)),
            load_image("Uccello2.PNG", size=(70, 70)),
            load_image("Uccello3.PNG", size=(70, 70)),
            load_image("Uccello4.PNG", size=(70, 70)),
        ]
        # right-facing birds
        self.img_birds_right = [
            load_image("RUccello01.png", "RUccello1.png", size=(70, 70)),
            load_image("RUccello3.png", size=(70, 70)),
            load_image("RUccello4.png", size=(70, 70)),
        ]
        self.img_cloud = load_image("NUVOLA2.PNG", "NUVOLA.PNG", size=(140, 80))
        self.img_island = load_image("ISOLA.PNG", "PALMA.PNG", size=(400, 400))
        self.img_start = load_image("START.PNG", size=(440, 440))
        self.img_gameover = load_image("GAMEOVER.png", size=(400, 400))
        self.img_win = load_image("YOU_WIN.png", size=(400, 400))

    # ------------------------------------------------------------ reset
    def reset(self, full=False):
        self.state = MENU if not AUTOTEST else PLAYING
        self.level_index = 0
        self.score = 0
        self.lives = 3
        self.start_level(0)
        if full:
            self.running = True

    def start_level(self, idx):
        self.level_index = idx
        self.level = LEVELS[idx]
        self.altitude = float(self.level["altitude"])
        if AUTOTEST:
            self.altitude = 120.0   # shrink levels so the smoke test is fast
        self.player = Player(self.img_player)
        self.obstacles = []
        self.floaters = []
        self.clouds_back = [Cloud(self.img_cloud) for _ in range(5)]
        self.clouds_front = [Cloud(self.img_cloud) for _ in range(4)]
        self.heli_timer = random.uniform(0.5, self.level["heli_rate"])
        self.bird_timer = random.uniform(1.0, self.level["bird_rate"])
        # wind
        self.wind = 0.0
        self.wind_target = 0.0
        self.gust_timer = random.uniform(3.0, 6.0)
        # landing phase
        self.island_y = float(SCREEN_H + 80)
        self.landed_msg = ""
        self.state_timer = 0.0

    # --------------------------------------------------------- spawning
    def spawn_heli(self):
        going_right = random.random() < 0.5
        speed = random.uniform(60, 110) + 15 * self.level_index
        img = random.choice(self.img_helis_flipped if going_right else self.img_helis)
        x = -260 if going_right else SCREEN_W + 40
        y = SCREEN_H + random.randint(20, 240)
        self.obstacles.append(Obstacle(img, x, y, speed if going_right else -speed, "heli"))

    def spawn_bird(self, flock=False):
        going_right = random.random() < 0.5
        speed = random.uniform(140, 220) + 20 * self.level_index
        imgs = self.img_birds_right if going_right else self.img_birds_left
        vx = speed if going_right else -speed
        base_x = -80 if going_right else SCREEN_W + 10
        base_y = SCREEN_H + random.randint(20, 200)
        n = 3 if flock else 1
        for i in range(n):
            img = random.choice(imgs)
            dx = -i * 60 if going_right else i * 60
            self.obstacles.append(Obstacle(img, base_x + dx, base_y + i * 45, vx, "bird"))

    # ------------------------------------------------------------ update
    def update_playing(self, dt, keys):
        lv = self.level

        # wind gusts
        if lv["wind"] > 0:
            self.gust_timer -= dt
            if self.gust_timer <= 0:
                if self.wind_target == 0:
                    self.wind_target = random.uniform(0.5, 1.0) * lv["wind"] * random.choice((-1, 1))
                    self.gust_timer = random.uniform(1.5, 3.0)   # gust duration
                else:
                    self.wind_target = 0.0
                    self.gust_timer = random.uniform(3.0, 6.5)   # calm period
        self.wind += (self.wind_target - self.wind) * min(1.0, 3.0 * dt)

        scroll = lv["fall"]
        self.player.update(dt, keys, self.wind)

        # altitude + score
        self.altitude -= scroll * dt * 0.5           # ~0.5 m per px, feels right
        self.score += 12 * (self.level_index + 1) * dt

        # spawn obstacles
        self.heli_timer -= dt
        if self.heli_timer <= 0:
            self.spawn_heli()
            self.heli_timer = random.uniform(0.6, 1.4) * lv["heli_rate"]
        if lv["bird_rate"] < 60:
            self.bird_timer -= dt
            if self.bird_timer <= 0:
                self.spawn_bird(flock=random.random() < lv["flock"])
                self.bird_timer = random.uniform(0.6, 1.4) * lv["bird_rate"]

        # clouds
        for c in self.clouds_back + self.clouds_front:
            c.update(dt, scroll)

        # obstacles + collisions
        prect = pygame.Rect(self.player.x, self.player.y, self.player.w, self.player.h)
        for ob in self.obstacles:
            ob.update(dt, scroll)
            if self.player.invincible <= 0 and ob.collides(self.player):
                self.hit(ob)
            elif (not ob.near_missed
                  and ob.y + ob.h < self.player.y
                  and ob.rect().inflate(70, 70).colliderect(prect)):
                ob.near_missed = True
                self.score += 25
                self.floaters.append(FloatingText("+25", self.player.x + 30, self.player.y - 10))
        self.obstacles = [o for o in self.obstacles if not o.dead]

        for f in self.floaters:
            f.update(dt)
        self.floaters = [f for f in self.floaters if f.life > 0]

        # level finished?
        if self.altitude <= 0:
            if self.level_index == len(LEVELS) - 1:
                self.state = LANDING
                self.obstacles = []
                if AUTOTEST:
                    self.player.x = 200  # guarantee a landing in the smoke test
            else:
                self.score += 200 * (self.level_index + 1)
                self.state = LEVEL_CLEAR
                self.state_timer = 2.2

    def hit(self, obstacle):
        self.lives -= 1
        self.floaters.append(FloatingText("OUCH!", self.player.x + 20, self.player.y - 20, (255, 80, 80)))
        if obstacle.kind == "bird":
            obstacle.dead = True
        if self.lives <= 0:
            self.state = GAME_OVER
        else:
            self.player.invincible = 2.0

    def update_landing(self, dt, keys):
        # island rises to its resting spot, then the player drops onto it
        target = 300
        if self.island_y > target:
            self.island_y = max(target, self.island_y - self.level["fall"] * dt)
            self.player.update(dt, keys, self.wind * 0.5)
        else:
            self.player.update(dt, keys, 0)
            self.player.y += 130 * dt
            for c in self.clouds_back + self.clouds_front:
                c.update(dt, 10)
            if self.player.y >= 520:
                feet = self.player.center_x
                isl_left, isl_right = 100 + 35, 100 + 365
                x_left, x_right = 100 + 95, 100 + 215
                if isl_left <= feet <= isl_right:
                    self.player.y = 520
                    if x_left <= feet <= x_right:
                        self.score += 500
                        self.landed_msg = "PERFECT LANDING ON THE X!  +500"
                    else:
                        self.score += 150
                        self.landed_msg = "Safe landing!  +150"
                    self.state = WIN
                else:
                    if self.player.y >= 600:
                        self.landed_msg = "SPLASH! You missed the island..."
                        self.state = GAME_OVER

    # -------------------------------------------------------------- menu
    def update_menu(self, dt):
        self.menu_time += dt
        for c in self.menu_clouds:
            c.x += c.drift * dt
            if c.x > SCREEN_W + 60:
                c.x = -160
            elif c.x < -160:
                c.x = SCREEN_W + 60
        # a bird crosses the screen every few seconds
        self.menu_bird_timer -= dt
        if self.menu_bird_timer <= 0:
            going_right = random.random() < 0.5
            imgs = self.img_birds_right if going_right else self.img_birds_left
            vx = random.uniform(90, 160) * (1 if going_right else -1)
            x = -80 if going_right else SCREEN_W + 10
            self.menu_birds.append(
                Obstacle(random.choice(imgs), x, random.randint(420, 700), vx, "bird"))
            self.menu_bird_timer = random.uniform(2.5, 5.0)
        for b in self.menu_birds:
            b.x += b.vx * dt
            b.y += math.sin(self.menu_time * 4 + b.y) * 12 * dt
        self.menu_birds = [b for b in self.menu_birds
                           if -120 < b.x < SCREEN_W + 120]

    def draw_menu(self):
        s = self.screen
        t = self.menu_time
        s.blit(self.menu_gradient, (0, 0))

        # twinkling stars in the upper sky
        random.seed(42)
        for _ in range(40):
            sx, sy = random.randint(0, SCREEN_W), random.randint(0, 280)
            tw = 0.5 + 0.5 * math.sin(t * random.uniform(1.0, 3.0) + sx)
            c = int(120 + 130 * tw)
            pygame.draw.circle(s, (c, c, min(255, c + 20)), (sx, sy), 1)
        random.seed()

        for c in self.menu_clouds[:4]:
            c.draw(s)
        for b in self.menu_birds:
            b.draw(s)

        # the skydiver gently swings down the screen
        px = SCREEN_W / 2 - self.img_player.get_width() / 2 + math.sin(t * 0.7) * 110
        py = 400 + math.sin(t * 1.6) * 18
        rot = math.sin(t * 0.7 + 1.2) * 8
        rotated = pygame.transform.rotozoom(self.img_player, rot, 1.0)
        s.blit(rotated, (px - (rotated.get_width() - self.img_player.get_width()) / 2,
                         py - (rotated.get_height() - self.img_player.get_height()) / 2))

        for c in self.menu_clouds[4:]:
            c.draw(s)

        # logo with a soft bounce
        logo_y = 90 + math.sin(t * 1.4) * 8
        s.blit(self.img_start, (SCREEN_W / 2 - self.img_start.get_width() / 2, logo_y))

        # pulsing start hint
        pulse = 150 + int(105 * (0.5 + 0.5 * math.sin(t * 3.5)))
        hint = self.big_font.render("PRESS  S", True, (255, 255, 255))
        hint.set_alpha(pulse)
        s.blit(hint, (SCREEN_W / 2 - hint.get_width() / 2, 560))

        # bottom info panel
        panel = pygame.Surface((SCREEN_W, 120), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 130))
        s.blit(panel, (0, SCREEN_H - 120))
        lines = [
            "ARROWS / A-D  move      P  pause      R  restart      H  show hitboxes",
            "Dodge helicopters and birds through 5 levels of open sky.",
            "Survive the wind, then land on the X for a perfect landing!",
        ]
        y = SCREEN_H - 105
        for line in lines:
            img = self.small_font.render(line, True, (225, 225, 235))
            s.blit(img, (SCREEN_W / 2 - img.get_width() / 2, y))
            y += 26

    def draw_hitbox_outline(self, mask, x, y):
        pts = mask.outline(6)
        if len(pts) > 2:
            pygame.draw.lines(self.screen, (255, 60, 60), True,
                              [(px + x, py + y) for px, py in pts], 2)

    # ------------------------------------------------------------- draw
    def draw_hud(self):
        s = self.screen
        bar = pygame.Surface((SCREEN_W, 46), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 110))
        s.blit(bar, (0, 0))
        s.blit(self.font.render(f"LEVEL {self.level_index + 1}/{len(LEVELS)}  {self.level['name']}",
                                True, (255, 255, 255)), (10, 10))
        score_txt = self.font.render(f"SCORE {int(self.score)}", True, (255, 230, 90))
        s.blit(score_txt, (SCREEN_W - score_txt.get_width() - 10, 10))
        for i in range(self.lives):
            draw_heart(s, 10 + i * 26, 50)
        # altitude bar
        frac = max(0.0, self.altitude / self.level["altitude"]) if not AUTOTEST else 0.5
        pygame.draw.rect(s, (255, 255, 255), (SCREEN_W - 26, 60, 14, 300), 2, border_radius=6)
        h = int(296 * frac)
        pygame.draw.rect(s, (90, 220, 120), (SCREEN_W - 24, 62 + (296 - h), 10, h), border_radius=5)
        alt = self.small_font.render(f"{int(max(0, self.altitude))} m", True, (255, 255, 255))
        s.blit(alt, (SCREEN_W - 30 - alt.get_width(), 60))
        # wind indicator
        if abs(self.wind) > 8:
            direction = ">>>" if self.wind > 0 else "<<<"
            w = self.font.render(f"WIND {direction}", True, (255, 160, 60))
            s.blit(w, (SCREEN_W / 2 - w.get_width() / 2, 52))

    def draw_world(self, with_island=False):
        s = self.screen
        s.blit(self.gradients[self.level_index], (0, 0))
        for c in self.clouds_back:
            c.draw(s)
        if with_island:
            pygame.draw.rect(s, (20, 80, 200), (0, self.island_y + 310, SCREEN_W, SCREEN_H))
            pygame.draw.rect(s, (30, 110, 220), (0, self.island_y + 360, SCREEN_W, SCREEN_H))
            s.blit(self.img_island, (100, self.island_y))
        for ob in self.obstacles:
            ob.draw(s)
        self.player.draw(s)
        if self.show_hitboxes:
            for ob in self.obstacles:
                self.draw_hitbox_outline(ob.mask, ob.x, ob.y)
            self.draw_hitbox_outline(self.player.mask, self.player.x, self.player.y)
        for c in self.clouds_front:
            c.draw(s)
        for f in self.floaters:
            f.draw(s, self.font)

    def draw_center_text(self, lines, dy=0):
        y = SCREEN_H // 2 + dy
        for line, font, color in lines:
            img = font.render(line, True, color)
            self.screen.blit(img, (SCREEN_W / 2 - img.get_width() / 2, y))
            y += img.get_height() + 8

    # -------------------------------------------------------------- run
    def run(self):
        frames = 0
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            keys = pygame.key.get_pressed()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_s and self.state == MENU:
                        self.state = PLAYING
                    elif event.key == pygame.K_p and self.state in (PLAYING, PAUSED):
                        self.state = PAUSED if self.state == PLAYING else PLAYING
                    elif event.key == pygame.K_r and self.state in (GAME_OVER, WIN):
                        self.reset()
                    elif event.key == pygame.K_h:
                        self.show_hitboxes = not self.show_hitboxes
                    elif event.key == pygame.K_ESCAPE:
                        self.running = False

            # ---------------- update ----------------
            if self.state == MENU:
                self.update_menu(dt)
            elif self.state == PLAYING:
                self.update_playing(dt, keys)
            elif self.state == LANDING:
                self.update_landing(dt, keys)
            elif self.state == LEVEL_CLEAR:
                self.state_timer -= dt
                if self.state_timer <= 0:
                    self.start_level(self.level_index + 1)
                    self.state = PLAYING

            # ---------------- draw ----------------
            if self.state == MENU:
                self.draw_menu()
            elif self.state in (PLAYING, PAUSED):
                self.draw_world()
                self.draw_hud()
                if self.state == PAUSED:
                    self.draw_center_text([("PAUSED", self.big_font, (255, 255, 255))], dy=-40)
            elif self.state == LEVEL_CLEAR:
                self.draw_world()
                self.draw_hud()
                nxt = LEVELS[self.level_index + 1]["name"]
                self.draw_center_text([
                    ("LEVEL CLEAR!", self.big_font, (120, 255, 140)),
                    (f"+{200 * (self.level_index + 1)} bonus", self.font, (255, 230, 90)),
                    (f"Next: {nxt}", self.font, (255, 255, 255)),
                ], dy=-60)
            elif self.state == LANDING:
                self.draw_world(with_island=True)
                self.draw_hud()
                self.draw_center_text([("LAND ON THE ISLAND!", self.font, (255, 255, 255))], dy=-300)
            elif self.state == GAME_OVER:
                self.draw_world(with_island=self.island_y < SCREEN_H)
                self.screen.blit(self.img_gameover, (100, 120))
                self.draw_center_text([
                    (self.landed_msg or "You crashed!", self.font, (255, 200, 200)),
                    (f"FINAL SCORE: {int(self.score)}", self.font, (255, 230, 90)),
                    ("Press R to try again", self.font, (255, 255, 255)),
                ], dy=160)
            elif self.state == WIN:
                self.draw_world(with_island=True)
                self.screen.blit(self.img_win, (100, 60))
                self.draw_center_text([
                    (self.landed_msg, self.font, (160, 255, 180)),
                    (f"FINAL SCORE: {int(self.score)}", self.font, (255, 230, 90)),
                    ("Press R to play again", self.font, (255, 255, 255)),
                ], dy=120)

            pygame.display.flip()

            # ---------------- headless smoke test ----------------
            if AUTOTEST:
                frames += 1
                if self.state == WIN:
                    print("AUTOTEST: reached WIN state, score", int(self.score))
                    self.running = False
                if frames > 6000:
                    print("AUTOTEST: timeout in state", self.state)
                    self.running = False

        pygame.quit()


if __name__ == "__main__":
    Game().run()
