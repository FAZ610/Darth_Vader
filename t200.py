"""t200: survival-first baseline.

Strategy, in priority order:
  1. Zone. Every point inside the NEXT circle stays inside the shrinking circle for the
     whole shrink (circles are nested and convex), so the bot's home is the next circle
     minus a margin. It computes the exact time the moving edge reaches it and leaves
     early enough to walk (not boost) there. Loot detours are only taken when the slack allows.
  2. Don't get hit. Dodge mortar impact points, sidestep lasers that are charging at us,
     face whoever hurt us (rear hits deal x1.5), retreat when low, and walk silently (< step_speed)
     when nothing is urgent.
  3. Grow cheaply. Supply drops (full HP + cubes), cubes, weapon pickups, and crates, but only
     inside the safe area and only when reachable without crossing walls.
  4. Fight defensively. Shoot only at mechs that are close or already hurting us, with
     lead, line-of-sight checks, and per-weapon logic (gun, laser, lightning, mortar).

Map: buildings are rasterised from v2/world.json and ground heights read from v2/terrain.i16.
They are used for line-of-sight, wall avoidance, and a background BFS flow field toward the zone.
"""
import math
import os
import sys
import time
from array import array
from collections import deque

import mechfight as mf

TAU = 2 * math.pi


def wrap(a):
    return (a + math.pi) % TAU - math.pi


def norm(x, y):
    d = math.hypot(x, y)
    if d < 1e-9:
        return 0.0, 0.0
    return x / d, y / d


def hdist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# ----------------------------------------------------------------------------- map


class World:
    FINE = 2.0  # wall raster cell (m)
    COARSE = 6.0  # flow-field cell (m)

    def __init__(self, hello):
        self.ok = False
        self.flow_goal = None
        self.flow_dist = None
        self.flow_queue = None
        try:
            t0 = time.perf_counter()
            self._load(hello)
            self.ok = True
            mf.log("t200 map loaded in %.2fs" % (time.perf_counter() - t0))
        except Exception as exc:  # play without a map rather than crash
            mf.log("t200 map load failed: %r" % (exc,))

    # -- loading
    def _load(self, hello):
        import json

        files = hello["map"].get("files", ["v2/world.json", "v2/terrain.i16"])
        wpath = next((f for f in files if f.endswith(".json")), "v2/world.json")
        tpath = next((f for f in files if f.endswith(".i16")), "v2/terrain.i16")
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            hello["map"].get("dir", "/arena"), "/arena",
            os.path.join(here, "arena"), os.path.join(here, "mechfight-kit", "arena"),
        ]
        mdir = next((d for d in candidates if os.path.isfile(os.path.join(d, wpath))), candidates[0])
        with open(os.path.join(mdir, wpath), "r", encoding="utf-8") as fh:
            world = json.load(fh)

        ter = world["terrain"]
        self.tnx, self.tny = int(ter["nx"]), int(ter["ny"])
        self.tx0, self.ty0 = float(ter["minX"]), float(ter["minY"])
        self.tstep = float(ter["step"])
        self.tscale = float(ter.get("scale", 0.01))
        hgt = array("h")
        with open(os.path.join(mdir, tpath), "rb") as fh:
            hgt.frombytes(fh.read())
        if sys.byteorder == "big":
            hgt.byteswap()
        self.hgt = hgt

        b = world["bounds"]
        F = self.FINE
        self.x0, self.y0 = float(b["minX"]), float(b["minY"])
        self.x1, self.y1 = float(b["maxX"]), float(b["maxY"])
        self.nx = int(math.ceil((self.x1 - self.x0) / F)) + 1
        self.ny = int(math.ceil((self.y1 - self.y0) / F)) + 1
        n = self.nx * self.ny
        self.top = array("f", [-1e9]) * n
        self.base = array("f", [1e9]) * n
        for p in world["prisms"]:
            # Bridges are thin decks: walkable on top or under; ignore them as walls.
            if p.get("kind") == "bridge":
                continue
            rings = [p["ring"]] + list(p.get("holes") or [])
            self._fill(rings, float(p["top"]), float(p["base"]))

        # coarse walkability for the flow field
        C = self.COARSE
        self.cnx = int(math.ceil((self.x1 - self.x0) / C))
        self.cny = int(math.ceil((self.y1 - self.y0) / C))
        cb = bytearray(self.cnx * self.cny)
        for j in range(self.cny):
            cy = self.y0 + (j + 0.5) * C
            for i in range(self.cnx):
                cx = self.x0 + (i + 0.5) * C
                if (
                    cx < self.x0 + 4 or cx > self.x1 - 4 or cy < self.y0 + 4 or cy > self.y1 - 4
                ):
                    cb[j * self.cnx + i] = 1
                    continue
                g = self.ground(cx, cy)
                for ox, oy in ((0, 0), (2.2, 0), (-2.2, 0), (0, 2.2), (0, -2.2)):
                    if self.wall_at(cx + ox, cy + oy, g, 9.0):
                        cb[j * self.cnx + i] = 1
                        break
        self.cblock = cb

    def _fill(self, rings, top, base):
        F = self.FINE
        edges = []
        ymin, ymax = 1e18, -1e18
        for r in rings:
            m = len(r) // 2
            for k in range(m):
                xa, ya = r[2 * k], r[2 * k + 1]
                xb, yb = r[2 * ((k + 1) % m)], r[2 * ((k + 1) % m) + 1]
                edges.append((xa, ya, xb, yb))
                ymin = min(ymin, ya)
                ymax = max(ymax, ya)
        j0 = max(0, int(math.ceil((ymin - self.y0) / F)))
        j1 = min(self.ny - 1, int(math.floor((ymax - self.y0) / F)))
        topa, basea, nx = self.top, self.base, self.nx
        for j in range(j0, j1 + 1):
            y = self.y0 + j * F
            xs = []
            for xa, ya, xb, yb in edges:
                if (ya <= y) != (yb <= y):
                    xs.append(xa + (y - ya) * (xb - xa) / (yb - ya))
            if len(xs) < 2:
                continue
            xs.sort()
            row = j * nx
            for k in range(0, len(xs) - 1, 2):
                i0 = max(0, int(math.ceil((xs[k] - self.x0) / F)))
                i1 = min(nx - 1, int(math.floor((xs[k + 1] - self.x0) / F)))
                for i in range(i0, i1 + 1):
                    idx = row + i
                    if top > topa[idx]:
                        topa[idx] = top
                    if base < basea[idx]:
                        basea[idx] = base

    # -- queries
    def ground(self, x, y):
        fx = (x - self.tx0) / self.tstep
        fy = (y - self.ty0) / self.tstep
        i = min(max(int(fx), 0), self.tnx - 2)
        j = min(max(int(fy), 0), self.tny - 2)
        ax = min(max(fx - i, 0.0), 1.0)
        ay = min(max(fy - j, 0.0), 1.0)
        h = self.hgt
        k = j * self.tnx + i
        h00, h10 = h[k], h[k + 1]
        h01, h11 = h[k + self.tnx], h[k + self.tnx + 1]
        v = (h00 * (1 - ax) + h10 * ax) * (1 - ay) + (h01 * (1 - ax) + h11 * ax) * ay
        return v * self.tscale

    def _idx(self, x, y):
        i = int(round((x - self.x0) / self.FINE))
        j = int(round((y - self.y0) / self.FINE))
        if i < 0 or j < 0 or i >= self.nx or j >= self.ny:
            return -1
        return j * self.nx + i

    def wall_at(self, x, y, feet_z, height, step=1.2):
        idx = self._idx(x, y)
        if idx < 0:
            return True
        return self.top[idx] > feet_z + step and self.base[idx] < feet_z + height

    def solid_point(self, x, y, z):
        idx = self._idx(x, y)
        if idx < 0:
            return True
        return self.base[idx] < z < self.top[idx]

    def los(self, a, b, step=1.5):
        """Straight-line clearance from point a to point b (buildings + terrain)."""
        if not self.ok:
            return True
        dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        d = math.hypot(dx, dy)
        n = int(d / step)
        for k in range(1, n):
            f = k / n
            x, y, z = a[0] + dx * f, a[1] + dy * f, a[2] + dz * f
            if self.solid_point(x, y, z):
                return False
            if k % 2 == 0 and self.ground(x, y) > z + 0.5:
                return False
        return True

    def walk_clear(self, x, y, z, hx, hy, dist, height=9.0):
        """Can we walk dist meters along unit heading (hx, hy) at feet height z?"""
        if not self.ok:
            return True
        px, py = -hy, hx
        s = 2.0
        while s <= dist:
            cx, cy = x + hx * s, y + hy * s
            for off in (0.0, 1.8, -1.8):
                if self.wall_at(cx + px * off, cy + py * off, z, height):
                    return False
            s += 2.0
        return True

    # -- flow field (incremental BFS toward a goal, a few ms per tick)
    def _cidx(self, x, y):
        i = int((x - self.x0) / self.COARSE)
        j = int((y - self.y0) / self.COARSE)
        if i < 0 or j < 0 or i >= self.cnx or j >= self.cny:
            return -1
        return j * self.cnx + i

    def _ccenter(self, c):
        j, i = divmod(c, self.cnx)
        return self.x0 + (i + 0.5) * self.COARSE, self.y0 + (j + 0.5) * self.COARSE

    def set_flow_goal(self, gx, gy):
        if not self.ok:
            return
        c = self._cidx(gx, gy)
        if c < 0:
            return
        if self.cblock[c]:  # nearest free cell
            best, bd = -1, 1e18
            gi, gj = c % self.cnx, c // self.cnx
            for r in range(1, 12):
                for j in range(gj - r, gj + r + 1):
                    for i in range(gi - r, gi + r + 1):
                        if 0 <= i < self.cnx and 0 <= j < self.cny:
                            k = j * self.cnx + i
                            if not self.cblock[k]:
                                d = (i - gi) ** 2 + (j - gj) ** 2
                                if d < bd:
                                    best, bd = k, d
                if best >= 0:
                    break
            if best < 0:
                return
            c = best
        if c == self.flow_goal:
            return
        self.flow_goal = c
        self.flow_dist = array("i", [-1]) * (self.cnx * self.cny)
        self.flow_dist[c] = 0
        self.flow_queue = deque([c])

    def advance_flow(self, budget_s):
        q = self.flow_queue
        if not q:
            return
        end = time.perf_counter() + budget_s
        nx, ny = self.cnx, self.cny
        dist, blk = self.flow_dist, self.cblock
        count = 0
        while q:
            c = q.popleft()
            d = dist[c] + 1
            j, i = divmod(c, nx)
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ii, jj = i + di, j + dj
                if ii < 0 or jj < 0 or ii >= nx or jj >= ny:
                    continue
                k = jj * nx + ii
                if blk[k] or dist[k] >= 0:
                    continue
                if di and dj and (blk[j * nx + ii] or blk[jj * nx + i]):
                    continue  # no corner cutting
                dist[k] = d
                q.append(k)
            count += 1
            if count % 256 == 0 and time.perf_counter() > end:
                return

    def flow_heading(self, x, y, z):
        """Heading toward a reachable lower-distance cell nearby, or None."""
        if not self.ok or self.flow_dist is None:
            return None
        c = self._cidx(x, y)
        if c < 0 or self.flow_dist[c] < 0:
            return None
        if self.flow_dist[c] == 0:
            return None
        j0, i0 = divmod(c, self.cnx)
        best, bd = None, self.flow_dist[c]
        for r in (3, 2, 1):
            for j in range(j0 - r, j0 + r + 1):
                for i in range(i0 - r, i0 + r + 1):
                    if not (0 <= i < self.cnx and 0 <= j < self.cny):
                        continue
                    k = j * self.cnx + i
                    d = self.flow_dist[k]
                    if d < 0 or d >= bd:
                        continue
                    cx, cy = self._ccenter(k)
                    hx, hy = norm(cx - x, cy - y)
                    if self.walk_clear(x, y, z, hx, hy, math.hypot(cx - x, cy - y)):
                        best, bd = (hx, hy), d
            if best is not None:
                return best
        return None


# ----------------------------------------------------------------------------- bot

UPGRADE_BASE = {
    "armor": 100, "plating": 95, "nanites": 70,
    "gun_damage": 55, "gun_rate": 52, "laser_damage": 55, "laser_charge": 50,
    "lightning_efficiency": 50, "lightning_range": 42, "lightning_chain": 30,
    "servos": 48, "sensors": 44, "gyros": 38, "gun_mag": 36, "gun_velocity": 34,
    "jets": 32, "capacitor": 30, "reactor": 30,
    "mortar_reload": 34, "mortar_velocity": 28, "mortar_splash": 30, "laser_pierce": 15,
}
WEAPON_PREF = {"laser": 3, "lightning": 2, "mortar": 1, "gun": 0}
LOUD = {"gun", "laser", "laser_charge", "lightning", "mortar", "step", "boost", "jet", "reload"}


class Bot:
    name = "t200"

    def __init__(self, hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.slot = hello.get("slot", 0)
        self.world = World(hello)
        self.pickup_r = cfg["loot"]["pickup_radius"]
        self.cube_r = cfg["cubes"]["pickup_radius"]
        self.step_speed = cfg["sound"]["step_speed"]
        self.stat_cap = cfg["cubes"]["stat_cap"]
        self.attacked_by = {}  # id -> last time it damaged us
        self.threat = None  # (bearing, time)
        self.sound_threat = None  # (bearing, time)
        self.hist = deque()
        self.stuck_until = -1.0
        self.stuck_count = 0
        self.strafe_sign = 1
        self.strafe_flip = 0.0
        self.zone_start = None  # (phase key, center, radius)
        self.last_move = (0.0, 0.0)
        self.blocked_items = {}  # item id -> time we gave up

    # ---------------------------------------------------------------- zone model
    def zone_circle_fn(self, zone, t):
        """Return f(T) -> (cx, cy, r) for times T >= t, robust to whether the server
        reports the phase-start circle or the interpolated one during a shrink."""
        cx, cy = zone["center"]
        r = zone["radius"]
        nx, ny = zone["next_center"]
        nr = zone["next_radius"]
        s0, s1 = zone["shrink_start"], zone["shrink_end"]
        key = (round(nx, 2), round(ny, 2), round(nr, 2))
        if self.zone_start is None or self.zone_start[0] != key:
            self.zone_start = (key, (cx, cy), r, t < s0)
        _, start_c, start_r, seen_hold = self.zone_start
        interpolated = t > s0 and not (seen_hold and abs(start_r - r) < 0.01)
        if interpolated:
            a0, a1 = t, s1
        else:
            a0, a1 = s0, s1

        def at(T):
            if T <= a0 or a1 <= a0:
                f = 0.0 if T <= a0 else 1.0
            else:
                f = min(1.0, (T - a0) / (a1 - a0))
            return cx + (nx - cx) * f, cy + (ny - cy) * f, r + (nr - r) * f

        return at

    def zone_plan(self, obs, me):
        zone = obs["zone"]
        t = obs["t"]
        x, y = me["pos"][0], me["pos"][1]
        at = self.zone_circle_fn(zone, t)
        nx, ny = zone["next_center"]
        nr = zone["next_radius"]
        margin = min(0.25 * nr, 25.0)
        safe_r = max(nr - margin, 0.0)
        d_next = math.hypot(x - nx, y - ny)
        to_safe = max(0.0, d_next - safe_r)
        # earliest time the edge reaches our current position
        deadline = None
        T_end = max(zone["shrink_end"], t)
        cx, cy, r = at(t)
        if math.hypot(x - cx, y - cy) > r or not me["in_zone"]:
            deadline = t
        else:
            steps = 24
            for k in range(1, steps + 1):
                T = t + (T_end - t) * k / steps
                cx, cy, r = at(T)
                if math.hypot(x - cx, y - cy) > r - 3:
                    deadline = T
                    break
        walk = me["stats"]["walk_speed"]
        if deadline is None:
            slack = 1e9
        else:
            slack = deadline - t - to_safe / walk
        return {
            "nx": nx, "ny": ny, "safe_r": safe_r, "to_safe": to_safe,
            "slack": slack, "inside_safe": to_safe <= 0.0, "at": at,
            "outside": not me["in_zone"], "nr": nr,
        }

    def in_safe(self, zp, p, extra=0.0):
        return math.hypot(p[0] - zp["nx"], p[1] - zp["ny"]) <= zp["safe_r"] + extra

    def loot_ok(self, zp, p, t):
        """May we detour to point p?"""
        if self.in_safe(zp, p, 4.0):
            return True
        if zp["slack"] < 25:
            return False
        cx, cy, r = zp["at"](t + 15)
        return math.hypot(p[0] - cx, p[1] - cy) < r - 20

    # ---------------------------------------------------------------- upgrades
    def choose_upgrade(self, obs):
        me = obs["self"]
        hp_frac = me["hp"] / max(me["max_hp"], 1)
        threats = sum(1 for m in obs["mechs"] if m["kind"] == "mech")
        best, best_i = -1e9, 0
        for i, ch in enumerate(obs["offer"]["choices"]):
            cid = ch["id"]
            s = UPGRADE_BASE.get(cid, 20)
            if cid in ("armor", "plating") and (hp_frac < 0.5 or threats):
                s += 20
            if cid == "nanites" and hp_frac < 0.6 and not threats:
                s += 15
            if cid == "sensors" and obs["t"] < 120:
                s += 10
            if s > best:
                best, best_i = s, i
        return best_i

    # ---------------------------------------------------------------- aiming helpers
    def lead_point(self, me, tgt, speed):
        mx, my, mz = me["pos"]
        tx, ty, tz = tgt["pos"]
        vx, vy, vz = tgt.get("vel", [0, 0, 0])
        scale = 1 + self.cfg["cubes"]["size_per_cube"] * tgt.get("cubes", 0)
        com = (self.cfg["mech"]["height"] / 2) * scale if tgt["kind"] == "mech" else self.cfg["npc"]["height"] / 2
        px, py, pz = tx, ty, tz + com
        if speed:
            for _ in range(3):
                d = math.dist((px, py, pz), (mx, my, mz + me["stats"]["muzzle_height"]))
                tt = d / speed
                px, py = tx + vx * tt, ty + vy * tt
                pz = tz + com + (vz * tt if abs(vz) > 0.5 else 0)
        return px, py, pz

    def direct_aim(self, me, p):
        mx, my, mz = me["pos"]
        mz += me["stats"]["muzzle_height"]
        yaw = math.atan2(p[1] - my, p[0] - mx)
        pitch = math.atan2(p[2] - mz, math.hypot(p[0] - mx, p[1] - my))
        return [yaw, pitch]

    def mortar_aim(self, me, tgt, stats, high):
        v, g = stats["speed"], stats.get("gravity", 22)
        mx, my, mz = me["pos"]
        tube = mz + me["stats"]["height"] + 0.5
        tx, ty, tz = tgt["pos"]
        vx, vy, _ = tgt.get("vel", [0, 0, 0])
        px, py = tx, ty
        sol = None
        for _ in range(3):
            d = math.hypot(px - mx, py - my)
            h = tz - tube
            disc = v ** 4 - g * (g * d * d + 2 * h * v * v)
            if d < 1 or disc < 0:
                return None
            root = math.sqrt(disc)
            th = math.atan((v * v + root) / (g * d)) if high else math.atan((v * v - root) / (g * d))
            T = d / (v * math.cos(th))
            px, py = tx + vx * T, ty + vy * T
            sol = [math.atan2(py - my, px - mx), th]
        mp = self.cfg["mech"]
        if sol and mp["min_pitch"] <= sol[1] <= mp["max_pitch"]:
            return sol
        return None

    @staticmethod
    def aim_err(actual, want):
        return abs(wrap(actual[0] - want[0])) + 0.5 * abs(actual[1] - want[1])

    # ---------------------------------------------------------------- main
    def act(self, obs):
        t = obs["t"]
        me = obs["self"]
        mx, my, mz = me["pos"]
        hp_frac = me["hp"] / max(me["max_hp"], 1)
        energy = me["energy"]
        act = {"tick": obs["tick"]}
        W = self.world

        if obs.get("offer"):
            act["pick"] = self.choose_upgrade(obs)

        # ------------------------------------------------ memory from events/sounds
        for ev in obs.get("events", []):
            if ev.get("type") == "damaged":
                if ev.get("by") is not None:
                    self.attacked_by[ev["by"]] = t
                if ev.get("bearing") is not None:
                    self.threat = (ev["bearing"], t)
        for snd in obs.get("sounds", []):
            if snd["kind"] in LOUD and snd["dist"] in ("near", "mid") and snd.get("age", 0) < 1.0:
                if self.sound_threat is None or t - self.sound_threat[1] > 0.5 or snd["dist"] == "near":
                    self.sound_threat = (snd["bearing"], t)

        zp = self.zone_plan(obs, me)
        mechs = [m for m in obs["mechs"] if m["kind"] == "mech"]
        npcs = [m for m in obs["mechs"] if m["kind"] == "npc"]
        eye = (mx, my, mz + me["stats"]["eye_height"])
        muzzle = (mx, my, mz + me["stats"]["muzzle_height"])

        def recently(i, s=4.0):
            return t - self.attacked_by.get(i, -99) < s

        # ------------------------------------------------ target selection
        target, tscore = None, 1e9
        for m in mechs:
            d = hdist(m["pos"], me["pos"])
            hostile = recently(m["id"])
            weak = m.get("hp", 1e9) < 0.35 * m.get("max_hp", 1)
            if not (hostile or d < 90 or (weak and d < 150)):
                continue
            s = d - (80 if hostile else 0) - (40 if weak else 0)
            if s < tscore:
                target, tscore = m, s
        if target is None and not mechs:
            for n in npcs:
                d = hdist(n["pos"], me["pos"])
                if recently(n["id"], 5.0) or (d < 42 and hp_frac > 0.5):
                    if d < tscore:
                        target, tscore = n, d
        tgt_los = False
        tgt_d = 1e9
        if target is not None:
            tgt_d = hdist(target["pos"], me["pos"])
            tz = target["pos"][2] + 4.0
            tgt_los = W.los(muzzle, (target["pos"][0], target["pos"][1], tz))

        # crate as a fallback target (only when calm)
        crate = None
        if target is None and not mechs:
            best = 1e9
            for c in obs.get("crates", []):
                d = hdist(c["pos"], me["pos"])
                if d < 70 and abs(c["pos"][2] - mz) < 6 and self.loot_ok(zp, c["pos"], t):
                    if W.los(muzzle, (c["pos"][0], c["pos"][1], c["pos"][2] + 1.2)) and d < best:
                        crate, best = c, d

        # ------------------------------------------------ movement goal
        goal = None
        reason = "hold"
        urgent = zp["outside"] or zp["slack"] < 8
        visible_hostile = [m for m in mechs if hdist(m["pos"], me["pos"]) < 60 or recently(m["id"])]
        boost = False

        def reachable(p):
            hx, hy = norm(p[0] - mx, p[1] - my)
            d = hdist(p, me["pos"])
            return W.walk_clear(mx, my, mz, hx, hy, max(0.0, d - 3.0))

        def usable(item):
            gave_up = self.blocked_items.get(item["id"])
            return gave_up is None or t - gave_up > 8

        if not urgent:
            # supply drop: full HP + cubes
            for dr in obs.get("drops", []):
                p = dr["pos"]
                d = hdist(p, me["pos"])
                if dr.get("holder") not in (None, me["id"]) and dr.get("progress", 0) > 0:
                    continue
                eta = d / me["stats"]["walk_speed"]
                crowd = [m for m in mechs if hdist(m["pos"], p) < 35]
                if d < 170 and not crowd and self.loot_ok(zp, p, t) and eta > dr["lands_in"] - 6:
                    if hp_frac > 0.35 or not mechs:
                        goal, reason = (p[0], p[1]), "drop"
                        if d > dr["radius"] * 0.5:
                            boost = d > 40 and energy > 45
                        break
            # cubes
            if goal is None and me["cubes"] < 40:
                best = 1e9
                for c in obs.get("cubes", []):
                    d = hdist(c["pos"], me["pos"])
                    near_enemy = any(hdist(m["pos"], c["pos"]) < 25 for m in mechs)
                    if (d < 80 and abs(c["pos"][2] - mz) < 4 and not near_enemy and usable(c)
                            and self.loot_ok(zp, c["pos"], t) and d < best and reachable(c["pos"])):
                        goal, best, reason = (c["pos"][0], c["pos"][1]), d, "cube"
            # weapon pickups
            held = [w for w in me["weapons"] if w]
            held_kinds = {w["kind"] for w in held}
            free_slot = any(w is None for w in me["weapons"])
            if goal is None and free_slot:
                best = -1e9
                for pk in obs.get("pickups", []):
                    if pk["kind"] in held_kinds or pk["kind"] == "gun":
                        continue
                    d = hdist(pk["pos"], me["pos"])
                    s = WEAPON_PREF.get(pk["kind"], 0) * 15 - d
                    if (d < 80 and abs(pk["pos"][2] - mz) < 4 and usable(pk)
                            and self.loot_ok(zp, pk["pos"], t) and s > best and reachable(pk["pos"])):
                        goal, best, reason = (pk["pos"][0], pk["pos"][1]), s, "weapon"
            # walk toward a crate we're shooting
            if goal is None and crate is not None and hdist(crate["pos"], me["pos"]) > 15 and reachable(crate["pos"]):
                goal, reason = (crate["pos"][0], crate["pos"][1]), "crate"

        if goal is None:
            if not zp["inside_safe"] or zp["outside"]:
                goal, reason = (zp["nx"], zp["ny"]), "zone"
            else:
                # inside the safe disc: drift inward silently, then hold still
                d_c = math.hypot(mx - zp["nx"], my - zp["ny"])
                if d_c > 0.6 * max(zp["safe_r"], 1) and d_c > 6:
                    goal, reason = (zp["nx"], zp["ny"]), "drift"

        # flow field always tracks the zone target (cheap, incremental)
        W.set_flow_goal(zp["nx"], zp["ny"])
        W.advance_flow(0.008)

        mvx = mvy = 0.0
        speed_frac = 1.0
        if goal is not None:
            gd = math.hypot(goal[0] - mx, goal[1] - my)
            hx, hy = norm(goal[0] - mx, goal[1] - my)
            if reason in ("zone", "drift") and gd > 25:
                fh = W.flow_heading(mx, my, mz)
                if fh is not None:
                    hx, hy = fh
            mvx, mvy = hx, hy
            if reason == "drift":
                speed_frac = 0.38  # under step_speed: silent
            elif reason == "zone" and zp["slack"] > 30 and not zp["outside"]:
                speed_frac = 0.4
            if gd < 2.0:
                mvx = mvy = 0.0
            if reason in ("drop",) and gd < 3.0:
                mvx = mvy = 0.0

        # ------------------------------------------------ threats shape the movement
        dodge_x = dodge_y = 0.0
        # mortar shells: predict impact near our feet height
        mort = self.cfg["weapons"]["mortar"]
        for pr in obs.get("projectiles", []):
            px, py, pz = pr["pos"]
            vx, vy, vz = pr["vel"]
            if pr["kind"] == "mortar":
                g = mort.get("gravity", 22)
                a, b, c = -0.5 * g, vz, pz - mz
                disc = b * b - 4 * a * c
                if disc < 0:
                    continue
                tt = (-b - math.sqrt(disc)) / (2 * a)
                if tt < 0 or tt > 6:
                    continue
                ix, iy = px + vx * tt, py + vy * tt
                dd = math.hypot(ix - mx, iy - my)
                if dd < mort["splash_radius"] * 1.6 + 3:
                    ax, ay = norm(mx - ix, my - iy)
                    if ax == 0 and ay == 0:
                        ax, ay = -vy, vx
                        ax, ay = norm(ax, ay)
                    dodge_x += ax * 2
                    dodge_y += ay * 2
            else:
                # bullet: closest approach within 1 s
                rx, ry = mx - px, my - py
                vv = vx * vx + vy * vy
                if vv < 1:
                    continue
                tc = (rx * vx + ry * vy) / vv
                if 0 < tc < 1.0:
                    cx, cy = px + vx * tc - mx, py + vy * tc - my
                    if math.hypot(cx, cy) < 4:
                        sx, sy = norm(-vy, vx)
                        if sx * cx + sy * cy > 0:
                            sx, sy = -sx, -sy
                        dodge_x += sx * 0.7
                        dodge_y += sy * 0.7
        # laser charging at us: sidestep its line
        for m in mechs:
            if m.get("charging"):
                to_me = math.atan2(my - m["pos"][1], mx - m["pos"][0])
                if abs(wrap(m["aim"][0] - to_me)) < 0.25:
                    sx, sy = norm(-(my - m["pos"][1]), mx - m["pos"][0])
                    if sx * self.last_move[0] + sy * self.last_move[1] < 0:
                        sx, sy = -sx, -sy
                    dodge_x += sx * 1.5
                    dodge_y += sy * 1.5
                    boost = boost or energy > 20

        # under fire: break line of sight when low or outranged (cover beats trading shots)
        shooter = None
        for m in mechs:
            if recently(m["id"], 3.0) and (shooter is None or hdist(m["pos"], me["pos"]) < hdist(shooter["pos"], me["pos"])):
                shooter = m
        took_cover = False
        if shooter is not None and W.ok and not zp["outside"]:
            sd = hdist(shooter["pos"], me["pos"])
            if hp_frac < 0.6 or sd > 100:
                seye = (shooter["pos"][0], shooter["pos"][1], shooter["pos"][2] + 7.5)
                best, bs = None, 1e9
                if not W.los(seye, (mx, my, mz + 6.0), step=2.0):
                    # already hidden: stay put (silent) and let regen tick
                    mvx = mvy = 0.0
                    goal, reason = None, "hidden"
                    took_cover = True
                for dist_c in (() if took_cover else (10.0, 20.0, 32.0)):
                    for k in range(12):
                        a = k * TAU / 12
                        cx, cy = math.cos(a), math.sin(a)
                        px, py = mx + cx * dist_c, my + cy * dist_c
                        if not self.in_safe(zp, (px, py), 0.0) and zp["slack"] < 40:
                            continue
                        if not W.walk_clear(mx, my, mz, cx, cy, dist_c):
                            continue
                        pz = W.ground(px, py)
                        if W.los(seye, (px, py, pz + 6.0), step=2.0):
                            continue
                        s = dist_c - 0.05 * hdist((px, py), shooter["pos"])
                        if s < bs:
                            best, bs = (px, py), s
                    if best is not None:
                        break
                if best is not None:
                    goal, reason = best, "cover"
                    hx0, hy0 = norm(best[0] - mx, best[1] - my)
                    mvx, mvy = hx0, hy0
                    speed_frac = 1.0
                    boost = boost or energy > 25
                    took_cover = True
            if not took_cover:
                speed_frac = 1.0

        # combat stance: strafe while engaged; retreat when low
        if took_cover:
            pass
        elif target is not None and target["kind"] == "mech" and (tgt_d < 130 or recently(target["id"], 3.0)) and not urgent:
            if t > self.strafe_flip:
                self.strafe_sign = -self.strafe_sign
                self.strafe_flip = t + 1.2 + (self.slot % 5) * 0.15
            fx, fy = norm(target["pos"][0] - mx, target["pos"][1] - my)
            sx, sy = -fy * self.strafe_sign, fx * self.strafe_sign
            if hp_frac < 0.4 or tgt_d < 18:
                bx, by = -fx, -fy  # back off
                mvx, mvy = mvx * 0.4 + bx + sx * 0.5, mvy * 0.4 + by + sy * 0.5
                boost = boost or (energy > 30 and hp_frac < 0.4)
            else:
                mvx, mvy = mvx * 0.7 + sx * 0.8, mvy * 0.7 + sy * 0.8
            speed_frac = 1.0
        # avoid idle drones (don't aggro them)
        for n in npcs:
            if target is n:
                continue
            d = hdist(n["pos"], me["pos"])
            if d < 55 and not recently(n["id"], 5.0):
                ax, ay = norm(mx - n["pos"][0], my - n["pos"][1])
                w = (55 - d) / 55 * 1.5
                mvx += ax * w
                mvy += ay * w
                speed_frac = max(speed_frac, 0.8)

        mvx += dodge_x
        mvy += dodge_y
        if dodge_x or dodge_y:
            speed_frac = 1.0

        # keep combat/dodge motion from carrying us out of the safe disc
        if zp["nr"] > 0 and (mvx or mvy):
            nxp, nyp = mx + mvx * 5, my + mvy * 5
            if not self.in_safe(zp, (nxp, nyp), 2.0) and zp["slack"] < 40:
                ix, iy = norm(zp["nx"] - mx, zp["ny"] - my)
                dot = mvx * ix + mvy * iy
                if dot < 0:
                    mvx -= dot * ix * 1.2
                    mvy -= dot * iy * 1.2

        # zone urgency
        if zp["outside"] or zp["slack"] < 3:
            boost = boost or energy > 10
        if zp["outside"]:
            ix, iy = norm(zp["nx"] - mx, zp["ny"] - my)
            fh = W.flow_heading(mx, my, mz)
            if fh is not None:
                ix, iy = fh
            mvx, mvy = ix + dodge_x * 0.3, iy + dodge_y * 0.3
            speed_frac = 1.0

        # local wall avoidance
        hx, hy = norm(mvx, mvy)
        if hx or hy:
            if not W.walk_clear(mx, my, mz, hx, hy, 7.0):
                base_a = math.atan2(hy, hx)
                for k in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6):
                    a = base_a + k * 0.26
                    cx, cy = math.cos(a), math.sin(a)
                    if W.walk_clear(mx, my, mz, cx, cy, 7.0):
                        hx, hy = cx, cy
                        break
        # stuck detection: try jumping and jetting over, then sideways
        jump = False
        moving_cmd = (hx or hy) and speed_frac > 0.3
        self.hist.append((t, mx, my))
        while self.hist and t - self.hist[0][0] > 1.6:
            self.hist.popleft()
        if moving_cmd and t > self.stuck_until and len(self.hist) > 10:
            t0, x0, y0 = self.hist[0]
            if t - t0 > 1.4 and math.hypot(mx - x0, my - y0) < 1.5:
                self.stuck_until = t + 1.3
                self.stuck_count += 1
                self.hist.clear()
                if reason in ("cube", "weapon", "crate"):
                    for it in obs.get("cubes", []) + obs.get("pickups", []):
                        if goal and hdist(it["pos"], goal) < 1:
                            self.blocked_items[it["id"]] = t
        if t < self.stuck_until:
            if self.stuck_count % 2 == 0:
                a = math.atan2(hy, hx) + (1.2 if self.stuck_count % 4 == 0 else -1.2)
                hx, hy = math.cos(a), math.sin(a)
            jump = me["grounded"]
            boost = energy > 12
            speed_frac = 1.0

        # silent walking when nothing urgent
        if not boost and speed_frac < 1.0:
            spd = me["stats"]["walk_speed"]
            speed_frac = min(speed_frac, (self.step_speed * 0.92) / spd)
        if not (hx or hy):
            speed_frac = 0.0
        act["move"] = [hx * speed_frac, hy * speed_frac]
        # in the air with boost = jet; only jet when we mean to
        if not me["grounded"] and not (t < self.stuck_until or zp["outside"]):
            boost = False
        act["boost"] = bool(boost and (hx or hy or not me["grounded"]))
        act["jump"] = bool(jump)
        self.last_move = (hx, hy)

        # ------------------------------------------------ aim and fire
        fire = [False, False]
        weapons = me["weapons"]
        kinds = {w["kind"]: (i, w) for i, w in enumerate(weapons) if w}
        aim = None
        if target is not None:
            primary = None
            if "lightning" in kinds and tgt_los and tgt_d < kinds["lightning"][1]["stats"]["range"] * 0.9:
                primary = "lightning"
            elif "laser" in kinds and tgt_los and tgt_d < kinds["laser"][1]["stats"]["range"]:
                primary = "laser"
            elif "mortar" in kinds and 30 < tgt_d < 220 and (not tgt_los or tgt_d > 110):
                primary = "mortar"
            elif "gun" in kinds:
                primary = "gun"
            gun_speed = kinds["gun"][1]["stats"]["speed"] if "gun" in kinds else 252
            if primary == "mortar":
                aim = self.mortar_aim(me, target, kinds["mortar"][1]["stats"], high=not tgt_los)
            if aim is None:
                if primary == "laser":
                    aim = self.direct_aim(me, self.lead_point(me, target, 0))
                else:
                    aim = self.direct_aim(me, self.lead_point(me, target, gun_speed))
            actual = me["aim"]
            size = 2.5 if target["kind"] == "mech" else 1.8
            tol = math.atan2(size * 0.8, max(tgt_d, 1)) + 0.015
            for kind, (i, w) in kinds.items():
                st = w["stats"]
                if kind == "gun":
                    if not tgt_los or tgt_d > st["range"] * 0.95:
                        continue
                    want = self.direct_aim(me, self.lead_point(me, target, st["speed"]))
                    if w.get("reload", 0) == 0 and w.get("ammo", 0) > 0 and self.aim_err(actual, want) < tol * 1.5:
                        fire[i] = True
                elif kind == "lightning":
                    cone = math.radians(st.get("cone_deg", 30)) / 2
                    bearing = math.atan2(target["pos"][1] - my, target["pos"][0] - mx)
                    reserve = 25 if not zp["outside"] else 60
                    if (tgt_los and tgt_d < st["range"] * 0.95 and abs(wrap(actual[0] - bearing)) < cone * 0.8
                            and energy > st.get("energy", 3) + reserve):
                        fire[i] = True
                elif kind == "laser":
                    if not tgt_los or tgt_d > st["range"] or urgent:
                        continue
                    want = self.direct_aim(me, self.lead_point(me, target, 0))
                    charge = w.get("charge", 0)
                    full = st.get("charge", 0.75) * 0.97
                    if w.get("cooldown", 0) > 0:
                        continue
                    if charge < full:
                        fire[i] = self.aim_err(actual, want) < 0.6
                    else:
                        # release when on target (lead the beam: none needed)
                        fire[i] = self.aim_err(actual, want) > tol
                elif kind == "mortar":
                    if not (30 < tgt_d < 230) or w.get("cooldown", 0) > 0:
                        continue
                    want = self.mortar_aim(me, target, st, high=not tgt_los)
                    if want and self.aim_err(actual, want) < 0.04 and target["kind"] == "mech":
                        fire[i] = True
            mf.draw.line(list(muzzle), [target["pos"][0], target["pos"][1], target["pos"][2] + 4.5], "#ff5040")
        elif crate is not None:
            cp = (crate["pos"][0], crate["pos"][1], crate["pos"][2] + 1.2)
            aim = self.direct_aim(me, cp)
            d = hdist(crate["pos"], me["pos"])
            tol = math.atan2(1.0, max(d, 1)) + 0.01
            for kind, (i, w) in kinds.items():
                st = w["stats"]
                if kind == "gun" and w.get("reload", 0) == 0 and w.get("ammo", 0) > 0:
                    if self.aim_err(me["aim"], aim) < tol * 1.5 and d < st["range"]:
                        fire[i] = True
                elif kind == "lightning" and d < st["range"] * 0.9 and energy > 50:
                    fire[i] = abs(wrap(me["aim"][0] - aim[0])) < 0.2
        if aim is None:
            aim = self.scan_aim(t, me, mechs, zp, hx, hy)

        # gun housekeeping: reload when empty or when calm and low
        if "gun" in kinds:
            i, w = kinds["gun"]
            if w.get("reload", 0) == 0:
                mag = w["stats"].get("mag", 12)
                if w.get("ammo", 0) == 0 or (target is None and not mechs and w.get("ammo", 0) < mag * 0.6):
                    act["reload"] = True
                    fire[i] = False

        # ------------------------------------------------ take weapons in reach
        free_slot = any(w is None for w in weapons)
        best_pk = None
        for pk in obs.get("pickups", []):
            if pk["kind"] == "gun" or pk["kind"] in kinds:
                continue
            if hdist(pk["pos"], me["pos"]) <= self.pickup_r - 0.3 and abs(pk["pos"][2] - mz) < 3.8:
                if best_pk is None or WEAPON_PREF.get(pk["kind"], 0) > WEAPON_PREF.get(best_pk["kind"], 0):
                    best_pk = pk
        if best_pk is not None:
            if free_slot:
                act["take"] = best_pk["id"]
            else:
                # swap a weaker non-gun weapon for a better one (never while charging)
                for kind, (i, w) in kinds.items():
                    if kind == "gun" or (kind == "laser" and w.get("charge", 0) > 0):
                        continue
                    if WEAPON_PREF[best_pk["kind"]] > WEAPON_PREF.get(kind, 0) and target is None:
                        act["take"] = best_pk["id"]
                        act["drop"] = i
                        break

        act["aim"] = [wrap(aim[0]), max(self.cfg["mech"]["min_pitch"], min(self.cfg["mech"]["max_pitch"], aim[1]))]
        act["fire"] = fire

        if goal is not None:
            mf.draw.point([goal[0], goal[1], mz], "#40c0ff", 6)
        mf.draw.label("t200 %s hp%.0f e%.0f c%d sl%.0f" % (
            reason, me["hp"], energy, me["cubes"], min(zp["slack"], 999)))
        return act

    def scan_aim(self, t, me, mechs, zp, hx, hy):
        """No target: look where danger is most likely."""
        if self.threat and t - self.threat[1] < 3.0:
            return [self.threat[0], 0.0]
        if mechs:
            m = min(mechs, key=lambda m: hdist(m["pos"], me["pos"]))
            return [math.atan2(m["pos"][1] - me["pos"][1], m["pos"][0] - me["pos"][0]), 0.0]
        if self.sound_threat and t - self.sound_threat[1] < 2.5:
            return [self.sound_threat[0], 0.0]
        # sweep: center on travel direction when moving, else on the zone center
        if hx or hy:
            base = math.atan2(hy, hx)
        else:
            base = math.atan2(zp["ny"] - me["pos"][1], zp["nx"] - me["pos"][0])
            if math.hypot(zp["ny"] - me["pos"][1], zp["nx"] - me["pos"][0]) < 10:
                base = 0.0
        phase = int(t / 1.1) % 4
        if not (hx or hy):
            return [base + (0.0, 2.1, 0.0, -2.1)[phase], 0.0]
        return [base + (0.0, 0.9, 0.0, -0.9)[phase], 0.0]


mf.run(Bot)
